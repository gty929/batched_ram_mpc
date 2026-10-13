"""Fetch a narrow, auditable EC2 Linux On-Demand price snapshot."""
import argparse
import csv
import datetime
import io
import json
import urllib.request
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--version', default='current', help='AWS offer version, e.g. 20261012193925; default refreshes current')
parser.add_argument('--output', type=Path, default=Path(__file__).with_suffix('.json'))
args = parser.parse_args()
URL = f'https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/{args.version}/us-east-1/index.csv'
WANTED = {'c7i.8xlarge', 'r7i.16xlarge', 'r6in.16xlarge', 'r8i.16xlarge', 'r8in.16xlarge', 'c8i.16xlarge', 'r7iz.16xlarge',
          'r6in.24xlarge', 'r6in.32xlarge', 'r8in.24xlarge', 'r8in.32xlarge',
          'r7i.24xlarge', 'r7i.48xlarge', 'r8i.24xlarge', 'r8i.32xlarge', 'r8i.48xlarge'}

with urllib.request.urlopen(URL, timeout=120) as response:
    text = io.TextIOWrapper(response, encoding='utf-8-sig', newline='')
    metadata = [next(text).strip() for _ in range(5)]
    reader = csv.DictReader(text)
    rows = []
    for row in reader:
        if (row.get('Instance Type') in WANTED and row.get('TermType') == 'OnDemand'
            and row.get('Operating System') == 'Linux' and row.get('Tenancy') == 'Shared'
            and row.get('Pre Installed S/W') == 'NA' and row.get('CapacityStatus') == 'Used'
            and row.get('Unit') == 'Hrs' and row.get('Location') == 'US East (N. Virginia)'):
            rows.append(row)

result = {'source_url': URL, 'fetched_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'feed_metadata': metadata, 'selected_rows': rows}
args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps({'metadata': metadata, 'count': len(rows), 'instances': [{key: row.get(key) for key in ('SKU', 'Instance Type', 'PricePerUnit', 'EffectiveDate', 'vCPU', 'Memory', 'Network Performance')} for row in rows]}, indent=2))
