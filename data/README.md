# Data

Phase 2A uses `raw/uploads/` for temporary streamed files, `raw/registered/` for immutable
checksum-named source bytes, `raw/rejected/` as a reserved rejected-file boundary, and
`manifests/` for future manifests. Directory placeholders remain tracked while uploaded
contents are ignored.

Registered files must not be edited or replaced. Re-submit changed bytes as a new source
file. Exact checksum duplicates are recorded as duplicate pipeline attempts without a
second raw file or database source-file row. CSV contents are not parsed or ingested yet.

Never place confidential data or credentials in this repository.
