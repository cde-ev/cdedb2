#!/usr/bin/env python3

"""Refresh the local template renderer dataset.

This works exclusively for offline deployments.
"""

import argparse
import json
import pathlib

import requests


def do_work(args):
    response = requests.get('https://localhost/db/event/offline/partial',
                            headers={'X-CdEDB-API-Token': "y1f2i3d4x5b6"},
                            verify='/etc/ssl/apache2/server.pem')
    if response.status_code != requests.codes.ok:
        print("Failed to communicate with local db instance. Aborting.")
        return
    data = response.json()
    if data['message'] != "success":
        print("Failed to retrieve data from the local db instance.")
        print(f"Error message: {data['message']}")
        return
    export = data['export']
    output_path = (args.basepath / 'cde_template_renderer_v3'
                   / 'partial_export_event.json')
    with open(output_path, 'w') as f:
        json.dump(export, f, indent=4)
        

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Refresh template renderer dataset.')
    args = parser.parse_args()

    args.basepath = pathlib.Path(__file__).parent 
    do_work(args)
