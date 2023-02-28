from collections import defaultdict
from copy import copy
from dataclasses import dataclass
from datetime import datetime, timedelta
import mmap
from operator import attrgetter
from typing import List, Optional, Dict

from datalog import datalog

@dataclass
class TreeNode:
    prefix: str
    entries: Optional[Dict[str, datalog.StartRecordData]] = None
    children: Optional[Dict[str, str]] = None


class LogFile:

    def __init__(self, filename):
        self.filename = filename
        self._entries = {}
        self._entry_series = {}

        self.load_file(self.filename)

    def load_file(self, filename):
        latest_timestamp = 0
        sync_timestamp = None
        sync_datetime = None
        with open(filename) as f:
            mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            reader = datalog.DataLogReader(mm)
            if not reader:
                raise Exception('Invalid data log file')
            for record in reader:
                timestamp = record.timestamp / 1000000
                latest_timestamp = timestamp
                if record.isStart():
                    data = record.getStartData()
                    self._entries[data.entry] = data
                    self._entry_series[data.entry] = []
                elif record.isFinish():
                    pass
                elif record.isSetMetadata():
                    pass
                elif record.isControl():
                    pass
                else:
                    entry = self._entries[record.entry]
                    if entry.name == 'systemTime' and entry.type == 'int64':
                        dt = datetime.fromtimestamp(record.getInteger() / 1000000)
                        sync_timestamp = timestamp
                        sync_datetime = dt
                        continue
                    if entry.type == 'double':
                        self._entry_series[record.entry].append([timestamp, record.getDouble()])
                    elif entry.type == 'int64':
                        self._entry_series[record.entry].append([timestamp, record.getInteger()])
                    elif entry.type == 'string' or entry.type == 'json':
                        self._entry_series[record.entry].append([timestamp, record.getString()])
                    elif entry.type == 'boolean':
                        self._entry_series[record.entry].append([timestamp, record.getBoolean()])
                    elif entry.type == 'boolean[]':
                        self._entry_series[record.entry].append([timestamp, record.getBooleanArray()])
                    elif entry.type == 'double[]':
                        self._entry_series[record.entry].append([timestamp, record.getDoubleArray()])
                    elif entry.type == 'float[]':
                        self._entry_series[record.entry].append([timestamp, record.getFloatArray()])
                    elif entry.type == 'int64[]':
                        self._entry_series[record.entry].append([timestamp, record.getIntegerArray()])
                    elif entry.type == 'string[]':
                        self._entry_series[record.entry].append([timestamp, record.getStringArray()])

        start_datetime = sync_datetime - timedelta(seconds=sync_timestamp)

        for e, s in self._entry_series.items():
            if not s:
                continue
            s.append([latest_timestamp, s[-1][1]])
            for record in s:
                try:
                    record[0] = start_datetime + timedelta(seconds=record[0])
                except OverflowError:
                    # Handle inexplicably large timestamps like 18446744069177.88. Since they only seem to appear at the
                    # beginning of log files, just treat them as zero.
                    record[0] = start_datetime

    def list_entries(self):
        return sorted(self._entries.values(), key=attrgetter('name'))

    def _get_entry_tree(self, this_prefix, entries, separator=':'):
        leaf_nodes = {}
        prefixes = defaultdict(list)

        for entry in entries:
            name = entry.name.lstrip('/')
            try:
                prefix, rest = name.split(separator, 1)
            except ValueError:
                leaf_nodes[name] = entry
                continue
            entry_copy = copy(entry)
            entry_copy.name = rest
            prefixes[prefix].append(entry_copy)

        children = {}
        for prefix, sub_entries in prefixes.items():
            children[prefix] = self._get_entry_tree(prefix, sub_entries, separator='/')

        return TreeNode(prefix=this_prefix, entries=leaf_nodes, children=children)

    def get_entry_tree(self):
        entries = self.list_entries()
        return self._get_entry_tree('', entries)

    def get_entry(self, entry_id):
        return self._entries[entry_id]

    def get_series(self, entry_id):
        return self._entry_series[entry_id]

    def get_record_count(self, entry_id):
        return max(len(self.get_series(entry_id)) - 1, 0)
