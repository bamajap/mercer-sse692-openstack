# -*- coding: utf-8 -*-
"""
Created on Sat Apr 23 22:56:51 2016

@author: jap
"""

# How you interact with OpenStack
from libcloud.compute.types import Provider
from libcloud.compute.providers import get_driver

auth_username = 'demo'
auth_password = 'password'
auth_url = 'http://192.168.1.100:5000'
project_name = 'demo'
region_name = 'RegionOne'
keypair_name = 'jap_sse692_key'
image_name = 'ubuntu-14.04-server-cloudimg-amd64-disk1'
flavor_id = 'd2'

provider = get_driver(Provider.OPENSTACK)
conn = provider(auth_username, auth_password,
                ex_force_auth_url=auth_url,
                ex_force_auth_version='2.0_password',
                ex_tenant_name=project_name,
                ex_force_service_region=region_name)

# Delete any previously created instances and security groups.
for instance in conn.list_nodes():
    if instance.name in ['all-in-one', 'app-worker-1', 'app-worker-2', 'app-controller', \
    'app-services', 'app-api-1', 'app-api-2', 'app-worker-1', 'app-worker-2', 'app-worker-3',]:
        print('Destroying Instance %s' % instance.name)
        conn.destroy_node(instance)

for group in conn.ex_list_security_groups():
    if group.name in ['control', 'worker', 'api', 'services']:
        print('Deleting security group: %s' % group.name)
        conn.ex_delete_security_group(group)

# Setup image and flavor
images = conn.list_images()
# Get the image from its name rather than its complex id.
image = [i for i in images if image_name in i.name][0]
flavor = conn.ex_get_size(flavor_id)

# Setup access key
print('Checking for existing SSH key pair...')
pub_key_file = '~/.ssh/{}.pub'.format(keypair_name)
keypair_exists = False
for keypair in conn.list_key_pairs():
    if keypair.name == keypair_name:
        keypair_exists = True

if keypair_exists:
    print('Keypair ' + keypair_name + ' already exists. Skipping import.')
else:
    print('adding keypair...')
    conn.import_key_pair_from_file(keypair_name, pub_key_file)

api_group = conn.ex_create_security_group('api', 'for API services only')
conn.ex_create_security_group_rule(api_group, 'TCP', 80, 80)
conn.ex_create_security_group_rule(api_group, 'TCP', 22, 22)

worker_group = conn.ex_create_security_group('worker', 'for services that run on a worker node \
(instance)')
conn.ex_create_security_group_rule(worker_group, 'TCP', 22, 22)

controller_group = conn.ex_create_security_group('control', 'for services that run on a control \
node')
conn.ex_create_security_group_rule(controller_group, 'TCP', 22, 22)
conn.ex_create_security_group_rule(controller_group, 'TCP', 80, 80)
conn.ex_create_security_group_rule(controller_group, 'TCP', 5672, 5672, \
                                                              source_security_group=worker_group)

services_group = conn.ex_create_security_group('services', 'for DB and AMQP services only')
conn.ex_create_security_group_rule(services_group, 'TCP', 22, 22)
conn.ex_create_security_group_rule(services_group, 'TCP', 3306, 3306, \
                                                                 source_security_group=api_group)
conn.ex_create_security_group_rule(services_group, 'TCP', 5672, 5672, \
                                                              source_security_group=worker_group)
conn.ex_create_security_group_rule(services_group, 'TCP', 5672, 5672, \
                                                                 source_security_group=api_group)

# Floating IP Helper Function
def get_floating_ip(conn):
    '''A helper function to re-use available Floating IPs'''
    unused_floating_ip = None
    for floating_ip in conn.ex_list_floating_ips():
        if not floating_ip.node_id:
            unused_floating_ip = floating_ip
            break
    if not unused_floating_ip:
        pool = conn.ex_list_floating_ip_pools()[0]
        unused_floating_ip = pool.create_floating_ip()
    return unused_floating_ip

# Add a central database and a messaging instance.  These will be used to track the state of \
# the fractals and to coordinate the communication between the services:
#   - install the RabbitMQ messaging service (-i messaging)
#   - install the central database service (-i database) 
userdata = '''#!/usr/bin/env bash
curl -L -s https://git.openstack.org/cgit/openstack/faafo/plain/contrib/install.sh | bash -s -- \
-i database -i messaging
'''

instance_services = conn.create_node(name='app-services',
                                     image=image,
                                     size=flavor,
                                     ex_keyname=keypair_name,
                                     ex_userdata=userdata,
                                     ex_security_groups=[services_group])
instance_services = conn.wait_until_running([instance_services])[0][0]
services_ip = instance_services.private_ips[0]

# Create multiple API instances to handle more fractal requests.
userdata = '''#!/usr/bin/env bash
curl -L -s https://git.openstack.org/cgit/openstack/faafo/plain/contrib/install.sh | bash -s -- \
-i faafo -r api -m 'amqp://guest:guest@%(services_ip)s:5672/' \
-d 'mysql://faafo:password@%(services_ip)s:3306/faafo'
''' % {'services_ip': services_ip}
instance_api_1 = conn.create_node(name='app-api-1',
                                  image=image,
                                  size=flavor,
                                  ex_keyname=keypair_name,
                                  ex_userdata=userdata,
                                  ex_security_groups=[api_group])
instance_api_2 = conn.create_node(name='app-api-2',
                                  image=image,
                                  size=flavor,
                                  ex_keyname=keypair_name,
                                  ex_userdata=userdata,
                                  ex_security_groups=[api_group])
instance_api_1 = conn.wait_until_running([instance_api_1])[0][0]
api_1_ip = instance_api_1.private_ips[0]
instance_api_2 = conn.wait_until_running([instance_api_2])[0][0]
api_2_ip = instance_api_2.private_ips[0]

for instance in [instance_api_1, instance_api_2]:
    floating_ip = get_floating_ip(conn)
    conn.ex_attach_floating_ip_to_node(instance, floating_ip)
    print('allocated %(ip)s to %(host)s' % {'ip': floating_ip.ip_address, 'host': instance.name})

# Create extra workers to create more fractals.
userdata = '''#!/usr/bin/env bash
curl -L -s https://git.openstack.org/cgit/openstack/faafo/plain/contrib/install.sh | bash -s -- \
-i faafo -r worker -e 'http://%(api_1_ip)s' -m 'amqp://guest:guest@%(services_ip)s:5672/'
''' % {'api_1_ip': api_1_ip, 'services_ip': services_ip}
instance_worker_1 = conn.create_node(name='app-worker-1',
                                     image=image,
                                     size=flavor,
                                     ex_keyname=keypair_name,
                                     ex_userdata=userdata,
                                     ex_security_groups=[worker_group])
instance_worker_2 = conn.create_node(name='app-worker-2',
                                     image=image,
                                     size=flavor,
                                     ex_keyname=keypair_name,
                                     ex_userdata=userdata,
                                     ex_security_groups=[worker_group])
instance_worker_3 = conn.create_node(name='app-worker-3',
                                     image=image,
                                     size=flavor,
                                     ex_keyname=keypair_name,
                                     ex_userdata=userdata,
                                     ex_security_groups=[worker_group])
