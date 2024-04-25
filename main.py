import meraki
import ipaddress
import re
import pandas as pd
import batch_helper
from tabulate import tabulate

import config

dashboard = meraki.DashboardAPI(config.api_key)

def print_tabulate(data):
    """
    Outputs a list of dictionaries in table format
    :param data: Dictionary to output
    :return:
    """
    print(tabulate(pd.DataFrame(data), headers='keys', tablefmt='fancy_grid'))

def determine_string_type(s):
    # Regex pattern for a basic FQDN validation
    fqdn_pattern = re.compile(r'^([a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}$')
    try:
        # Check if it's a valid IP address (IPv4 or IPv6)
        ipaddress.ip_address(s)
        s_type = "host"
        return s_type
    except ValueError:
        pass

    try:
        # Check if it's a valid subnet (IPv4 or IPv6)
        ipaddress.ip_network(s, strict=False)
        s_type = "cidr"
        return s_type
    except ValueError:
        pass

    if fqdn_pattern.match(s):
        s_type = "fqdn"
        return s_type
    s_type = "Unknown"
    return s_type

objects_pd = pd.read_csv("objects.csv")
objects_l_of_d = objects_pd.to_dict("records")

new_obj = []
print("Classifying objects in your CSV as follows... "
      "(Note: IPv6 objects are not supported at this time, and Unknown objects will be ignored).")
for obj in objects_l_of_d:
    result = determine_string_type(obj["object"])
    print(f"{obj['object']}: {result}")
    if result != "Unknown":
        if result == "cidr":
            net_address = ipaddress.ip_network(obj["object"], strict=False)
            if net_address.version != 6:
                item = {
                    "name": obj["object_name"],
                    "category": "network",
                    "type": "cidr",
                    "cidr": obj["object"],
                }
                new_obj.append(item)
        elif result == "host":
            ip_address = ipaddress.ip_address(obj["object"])
            if ip_address.version != 6:
                item = {
                    "name": obj["object_name"],
                    "category": "network",
                    "type": "cidr",
                    "cidr": obj["object"],
                }
                new_obj.append(item)
        elif result == "fqdn":
            item = {
                "name": obj["object_name"],
                "category": "network",
                "type": result,
                "fqdn": obj["object"]
            }
            new_obj.append(item)

existing_objects = [obj for obj in dashboard.organizations.getOrganizationPolicyObjects(config.org_id, total_pages=-1)
                    if obj['category']=="network"]

new_obj_set = set(obj["name"] for obj in new_obj)
existing_obj_set = set(obj["name"] for obj in existing_objects)
to_create = new_obj_set.difference(existing_obj_set)
to_update = new_obj_set.difference(to_create)

create_obj = [obj for obj in new_obj if obj["name"] in to_create]
update_obj = [obj for obj in new_obj if obj["name"] in to_update]
for u_obj in update_obj:
    for e_obj in existing_objects:
        if u_obj["name"]==e_obj["name"]:
            u_obj["policyObjectId"]=e_obj["id"]

create_obj_actions = []
for item in create_obj:
    kwargs = {k: item[k] for k in item.keys() - {"name", "category",
                                                 "type"}}
    create_object_action = dashboard.batch.organizations.createOrganizationPolicyObject(
        organizationId=config.org_id,
        name=item["name"],
        category=item["category"],
        type=item["type"],
        **kwargs
    )
    create_obj_actions.append(create_object_action)

update_obj_actions = []
for item in update_obj:
    kwargs = {k: item[k] for k in item.keys() - {"policyObjectId"}}
    update_object_action = dashboard.batch.organizations.updateOrganizationPolicyObject(
        organizationId=config.org_id,
        policyObjectId=item["policyObjectId"],
        **kwargs
    )
    update_obj_actions.append(update_object_action)

print("The following actions will be generated to create new policy objects: ")
print_tabulate(pd.DataFrame(create_obj_actions))
proceed = input("Proceed? (Y/N): ")

if proceed == 'Y':
    create_obj_helper = batch_helper.BatchHelper(dashboard, config.org_id, create_obj_actions,
                                           linear_new_batches=False, actions_per_new_batch=100)
    create_obj_helper.prepare()
    create_obj_helper.generate_preview()
    create_obj_helper.execute()

    print(f"Helper status is {create_obj_helper.status}")

    batches_report = dashboard.organizations.getOrganizationActionBatches(config.org_id)
    new_batches_statuses = [{'id': batch['id'], 'status': batch['status']} for batch
                            in batches_report if batch['id'] in create_obj_helper.submitted_new_batches_ids]
    failed_batch_ids = [batch['id'] for batch in new_batches_statuses if batch['status']['failed']]
    print(f'Failed batch IDs are as follows: {failed_batch_ids}')
else:
    print("Skipping creation of new policy objects due to user input.")

print("The following actions will be generated to update existing policy objects: ")
print_tabulate(pd.DataFrame(update_obj_actions))
proceed = input("Proceed? (Y/N): ")

if proceed == 'Y':
    upd_obj_helper = batch_helper.BatchHelper(dashboard, config.org_id, update_obj_actions,
                                           linear_new_batches=False, actions_per_new_batch=100)
    upd_obj_helper.prepare()
    upd_obj_helper.generate_preview()
    upd_obj_helper.execute()

    print(f"Helper status is {upd_obj_helper.status}")

    batches_report = dashboard.organizations.getOrganizationActionBatches(config.org_id)
    new_batches_statuses = [{'id': batch['id'], 'status': batch['status']} for batch
                            in batches_report if batch['id'] in upd_obj_helper.submitted_new_batches_ids]
    failed_batch_ids = [batch['id'] for batch in new_batches_statuses if batch['status']['failed']]
    print(f'Failed batch IDs are as follows: {failed_batch_ids}')
else:
    print("Skipping update of existing policy objects due to user input.")



