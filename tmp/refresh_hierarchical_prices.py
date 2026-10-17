"""Refresh the four prices used by the hierarchical ORAM estimate."""
import csv
import datetime
import io
import json
from pathlib import Path
import urllib.request

URL = 'https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/us-east-1/index.csv'
TARGET = Path('mpc_cost/data/aws_hierarchical_prices_2026-10-17.json')
with urllib.request.urlopen(URL, timeout=120) as response:
    lines = io.TextIOWrapper(response, encoding='utf-8-sig', newline='')
    metadata = [next(lines).strip() for _ in range(5)]
    rows = []
    for row in csv.DictReader(lines):
        if row.get('TermType') != 'OnDemand' or row.get('Location') != 'US East (N. Virginia)':
            continue
        is_instance = (row.get('Instance Type') == 'c6in.32xlarge'
            and row.get('Operating System') == 'Linux' and row.get('Tenancy') == 'Shared'
            and row.get('Pre Installed S/W') == 'NA' and row.get('CapacityStatus') == 'Used'
            and row.get('Unit') == 'Hrs')
        is_ebs = row.get('usageType') in {
            'EBS:VolumeUsage.gp3', 'EBS:VolumeP-IOPS.gp3', 'EBS:VolumeP-Throughput.gp3'}
        if is_instance or is_ebs:
            rows.append(row)
result = {
    'source_url': URL, 'access_date': '2026-10-17',
    'fetched_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'feed_metadata': metadata, 'selected_rows': rows,
    'region': 'us-east-1', 'currency': 'USD',
    'annualization': {'ec2_hours': 8760, 'ebs_months': 12},
    'storage_billing_unit_bytes': 2**30,
    'throughput_billing_unit_bytes_per_second': 2**20,
    'same_az_data_transfer_usd_per_GB': 0,
    'cross_az_data_transfer_usd_per_GB_in_plus_out': 0.02,
    'cross_az_transfer_billing_unit_bytes_assumed': 10**9,
    'documentation': {
        'gp3_price_and_binary_storage_units': 'https://docs.aws.amazon.com/prescriptive-guidance/latest/optimize-costs-microsoft-workloads/ebs-migrate-gp2-gp3.html',
        'gp3_performance_and_limits': 'https://docs.aws.amazon.com/ebs/latest/userguide/general-purpose.html',
        'same_az_transfer_across_accounts': 'https://docs.aws.amazon.com/vpc/latest/userguide/vpc-share-billing.html',
        'cross_az_transfer': 'https://aws.amazon.com/ec2/pricing/on-demand-backup/'
    }
}
assert len(rows) == 4, [(r.get('usageType'),r.get('Instance Type')) for r in rows]
TARGET.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
print(json.dumps({'path':str(TARGET), 'metadata':metadata,
    'prices':[{k:r.get(k) for k in ('SKU','Instance Type','usageType','Unit','PricePerUnit','EffectiveDate')} for r in rows]}, indent=2))
