# -*- coding: utf-8 -*-
"""
Created on Fri Apr 22 00:20:40 2016

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
image_name = 'Ubuntu QCOW2'

provider = get_driver(Provider.OPENSTACK)
conn = provider(auth_username, auth_password,
                ex_force_auth_url=auth_url, 
                ex_force_auth_version='2.0_password',
                ex_tenant_name=project_name,
                ex_force_service_region=region_name)

# Setup image and flavor
images = conn.list_images()
# Get the image from its name rather than its complex id.
image = [i for i in images if image_name in i.name][0]
flavor_id = '2'
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

for keypair in conn.list_key_pairs():
    print(keypair)

worker_group = conn.ex_create_security_group('worker', 'for services that run on a worker node \
(instance)')
conn.ex_create_security_group_rule(worker_group, 'TCP', 22, 22)

controller_group = conn.ex_create_security_group('control', 'for services that run on a control \
node')
conn.ex_create_security_group_rule(controller_group, 'TCP', 22, 22)
conn.ex_create_security_group_rule(controller_group, 'TCP', 80, 80)

# Create a rule that applies to only worker group instances.
conn.ex_create_security_group_rule(controller_group, 'TCP', 5672, 5672, \
                                                              source_security_group=worker_group)

# For the application instance, have the install script:
#   - install the RabbitMQ messaging service (-i messaging)
#   - install the Faafo (-i faafo) service
#   - enable the API service (-r api)
userdata = '''#!/usr/bin/env bash
curl -L -s https://git.openstack.org/cgit/openstack/faafo/plain/contrib/install.sh | bash -s -- \
-i faafo -i messaging -r api
'''

# Create controller instance to host the API, database, and messaging services.
instance_controller_1 = conn.create_node(name='app-controller',
                                         image=image,
                                         size=flavor,
                                         ex_keyname=keypair_name,
                                         ex_userdata=userdata,
                                         ex_security_groups=[controller_group])

conn.wait_until_running([instance_controller_1])

print('Checking for unused Floating IP...')
unused_floating_ip = None
for floating_ip in conn.ex_list_floating_ips():
    if not floating_ip.node_id:
        unused_floating_ip = floating_ip
        break

if not unused_floating_ip:
    pool = conn.ex_list_floating_ip_pools()[0]
    print('Allocating new Floating IP from pool: {}'.format(pool))
    unused_floating_ip = pool.create_floating_ip()

conn.ex_attach_floating_ip_to_node(instance_controller_1, unused_floating_ip)
print('Application will be deployed to http://%s' % unused_floating_ip.ip_address)

# Create a second instance that will be the worker instance.
instance_controller_1 = conn.ex_get_node_details(instance_controller_1.id)
if instance_controller_1.public_ips:
    ip_controller = instance_controller_1.private_ips[0]
else:
    ip_controller = instance_controller_1.public_ips[0]

# For the worker instance, have the install script:
#   - install the Faafo (-i faafo) services
#   - enable and start the worker service (-r worker)
#   - pass the address of the API instance (-e) and message queue (-m) so the
#     worker can pick up requests
#   - (optional) use the -d option to specify a database connection URL
userdata = '''#!/usr/bin/env bash
curl -L -s https://git.openstack.org/cgit/openstack/faafo/plain/contrib/install.sh | bash -s -- \
-i faafo -r worker -e 'http://%(ip_controller)s' \
-m 'amqp://guest:guest@%(ip_controller)s:5672/'
''' % {'ip_controller': ip_controller}

instance_worker_1 = conn.create_node(name='app-worker-1',
                                     image=image,
                                     size=flavor,
                                     ex_keyname=keypair_name,
                                     ex_userdata=userdata,
                                     ex_security_groups=[worker_group])

conn.wait_until_running([instance_worker_1])
print('Checking for unused Floating IP...')
unused_floating_ip = None
for floating_ip in conn.ex_list_floating_ips():
    if not floating_ip.node_id:
        unused_floating_ip = floating_ip
        break

if not unused_floating_ip:
    pool = conn.ex_list_floating_ip_pools()[0]
    print('Allocating new Floating IP from pool: {}'.format(pool))
    unused_floating_ip = pool.create_floating_ip()

conn.ex_attach_floating_ip_to_node(instance_worker_1, unused_floating_ip)
print('The worker will be available for SSH at %s' % unused_floating_ip.ip_address)