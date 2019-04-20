# -*- coding: utf-8 -*-
"""
Created on Thu Apr 21 22:55:11 2016

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

provider = get_driver(Provider.OPENSTACK)
conn = provider(auth_username, auth_password,
                ex_force_auth_url=auth_url, 
                ex_force_auth_version='2.0_password',
                ex_tenant_name=project_name,
                ex_force_service_region=region_name)

# Flavors and images
#images = conn.list_images()
#for image in images:
#    print(image)
#
#flavors = conn.list_sizes()
#for flavor in flavors:
#    print(flavor)

# Delete any previously created instances and security groups.
for instance in conn.list_nodes():
    if instance.name in ['all-in-one', 'app-worker-1', 'app-worker-2', \
                         'app-controller', 'app-services', 'app-api-1', 'app-api-2',\
                         'app-worker-1', 'app-worker-2', 'app-worker-3',]:
        print('Destroying Instance %s' % instance.name)
        conn.destroy_node(instance)

for group in conn.ex_list_security_groups():
    if group.name in ['control', 'worker', 'api', 'services']:
        print('Deleting security group: %s' % group.name)
        conn.ex_delete_security_group(group)
