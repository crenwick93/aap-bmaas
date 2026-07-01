#!/usr/bin/env python3
"""
Create a 'Bare Metal Server Request' catalog item on a ServiceNow PDI.

Reads credentials from the repo-root .env and builds:
  1. A 'Bare Metal Provisioning' category under the Service Catalog
  2. A 'Bare Metal Server Request' catalog item
  3. Three order-guide variables: hostname, ip_address, server_role

Usage:
    python3 ansible_deployment/scripts/setup-snow-catalog.py

Idempotent — skips objects that already exist.
"""

import json
import os
import sys
import warnings
from pathlib import Path
from urllib.parse import urljoin

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

import requests
from requests.auth import HTTPBasicAuth

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_env():
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        sys.exit(f"ERROR: {env_file} not found")
    env = {}
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, val = line.partition("=")
        env[key.strip()] = val.strip().strip('"').strip("'")
    return env


class SnowClient:
    def __init__(self, instance_url: str, username: str, password: str):
        self.base = instance_url.rstrip("/")
        self.auth = HTTPBasicAuth(username, password)
        self.headers = {"Content-Type": "application/json", "Accept": "application/json"}

    def get(self, table: str, query: str) -> list:
        url = f"{self.base}/api/now/table/{table}"
        r = requests.get(url, auth=self.auth, headers=self.headers,
                         params={"sysparm_query": query, "sysparm_limit": 1},
                         verify=False, timeout=30)
        r.raise_for_status()
        return r.json().get("result", [])

    def create(self, table: str, payload: dict) -> dict:
        url = f"{self.base}/api/now/table/{table}"
        r = requests.post(url, auth=self.auth, headers=self.headers,
                          data=json.dumps(payload), verify=False, timeout=30)
        r.raise_for_status()
        return r.json().get("result", {})


def get_or_create(client: SnowClient, table: str, query: str,
                  payload: dict, label: str) -> str:
    existing = client.get(table, query)
    if existing:
        sys_id = existing[0]["sys_id"]
        print(f"  [exists] {label} ({sys_id})")
        return sys_id
    result = client.create(table, payload)
    sys_id = result["sys_id"]
    print(f"  [created] {label} ({sys_id})")
    return sys_id


def main():
    env = load_env()
    instance = env.get("SERVICENOW_INSTANCE_URL", "")
    username = env.get("SERVICENOW_USERNAME", "")
    password = env.get("SERVICENOW_PASSWORD", "")

    if not all([instance, username, password]):
        sys.exit("ERROR: SERVICENOW_INSTANCE_URL, SERVICENOW_USERNAME, and "
                 "SERVICENOW_PASSWORD must be set in .env")

    client = SnowClient(instance, username, password)

    # Verify connectivity
    print(f"Connecting to {instance} ...")
    try:
        client.get("sys_properties", "name=instance_name")
    except requests.exceptions.RequestException as e:
        sys.exit(f"ERROR: Cannot reach ServiceNow: {e}")
    print("  Connected.\n")

    # 1. Find the default Service Catalog
    print("1. Locating Service Catalog ...")
    catalogs = client.get("sc_catalog", "title=Service Catalog")
    if not catalogs:
        sys.exit("ERROR: Default 'Service Catalog' not found on this instance")
    catalog_id = catalogs[0]["sys_id"]
    print(f"  [found] Service Catalog ({catalog_id})\n")

    # 2. Find the Hardware parent category, then create sub-category
    print("2. Setting up category under Hardware ...")
    hw_cats = client.get("sc_category", "title=Hardware^sc_catalog=" + catalog_id)
    if not hw_cats:
        sys.exit("ERROR: 'Hardware' category not found in Service Catalog")
    hw_category_id = hw_cats[0]["sys_id"]
    print(f"  [found] Hardware category ({hw_category_id})")

    category_id = get_or_create(
        client, "sc_category",
        "title=Bare Metal Provisioning^parent=" + hw_category_id,
        {"title": "Bare Metal Provisioning",
         "description": "Request physical server provisioning via Ansible Automation Platform",
         "sc_catalog": catalog_id,
         "parent": hw_category_id,
         "active": "true"},
        "Bare Metal Provisioning category"
    )
    print()

    # 3. Create catalog item
    print("3. Setting up catalog item ...")
    cat_item_id = get_or_create(
        client, "sc_cat_item",
        "name=Bare Metal Server Request",
        {"name": "Bare Metal Server Request",
         "category": category_id,
         "sc_catalogs": catalog_id,
         "short_description": "Provision a bare-metal RHEL 9 server via AAP and iDRAC",
         "description": (
             "Submit this request to provision a new bare-metal server with RHEL 9. "
             "The request is picked up automatically by Event-Driven Ansible, which "
             "triggers an end-to-end workflow: iDRAC boot-to-ISO, unattended install, "
             "RHSM registration, and demo application deployment."
         ),
         "active": "true",
         "ordered_item_link": "true"},
        "Bare Metal Server Request item"
    )
    print()

    # 4. Create catalog item variables
    print("4. Setting up order variables ...")

    variables = [
        {
            "name": "hostname",
            "question_text": "Hostname",
            "tooltip": "The hostname for the new server (e.g. t620-demo)",
            "default_value": "t620-demo",
            "order": 100,
            "type": 6,  # Single-line text
            "mandatory": "true",
        },
        {
            "name": "ip_address",
            "question_text": "IP Address",
            "tooltip": "Static IP to assign (e.g. 192.168.50.253)",
            "default_value": "192.168.50.253",
            "order": 200,
            "type": 6,
            "mandatory": "true",
        },
        {
            "name": "server_role",
            "question_text": "Server Role",
            "tooltip": "The role determines which post-provision configuration is applied",
            "default_value": "webserver",
            "order": 300,
            "type": 5,  # Select box
            "mandatory": "true",
            "choice_table": "",
        },
    ]

    for var in variables:
        var["cat_item"] = cat_item_id
        get_or_create(
            client, "item_option_new",
            f"name={var['name']}^cat_item={cat_item_id}",
            var,
            f"Variable: {var['name']}"
        )

    # Add choices for server_role
    role_var = client.get("item_option_new", f"name=server_role^cat_item={cat_item_id}")
    if role_var:
        role_var_id = role_var[0]["sys_id"]
        for idx, (value, label) in enumerate([
            ("webserver", "Web Server"),
            ("database", "Database Server"),
            ("appserver", "Application Server"),
        ]):
            get_or_create(
                client, "question_choice",
                f"question={role_var_id}^value={value}",
                {"question": role_var_id,
                 "text": label,
                 "value": value,
                 "order": (idx + 1) * 100},
                f"  Choice: {label}"
            )

    print(f"\nDone! Browse to: {instance}/nav_to.do?uri=com.glideapp.servicecatalog_cat_item_view.do?v=1&sysparm_id={cat_item_id}")
    print("Or open the Service Catalog in ServiceNow and look under 'Bare Metal Provisioning'.\n")


if __name__ == "__main__":
    main()
