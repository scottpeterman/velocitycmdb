
DELETE FROM capture_changes;
DELETE FROM capture_snapshots;
DELETE FROM sqlite_sequence WHERE name IN ('capture_changes', 'capture_snapshots');
VACUUM;
SELECT 'Changes cleared:', changes(), 'rows affected';  

rm -rf ~/.velocitycmdb/data/diffs/*