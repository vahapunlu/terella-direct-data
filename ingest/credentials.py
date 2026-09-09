"""Secrets never enter tracked files or output data."""
import os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def read_key(service):
 if service not in ('ads','cds'):raise ValueError('Unknown credential service')
 value=os.environ.get(service.upper()+'_API_KEY')
 if not value:value=(ROOT/f'.cache/credentials/{service}-key').read_text().strip()
 if not value or len(value)>200:raise ValueError('Missing API credential')
 return value
