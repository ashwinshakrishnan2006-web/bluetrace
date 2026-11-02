-- Runtime schema, created automatically by server.py.
CREATE TABLE IF NOT EXISTS incidents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created TEXT NOT NULL,
    result TEXT NOT NULL
);
-- result is a JSON snapshot containing validated inputs, predictions, evidence,
-- asset URLs, source regions and GeoJSON. PNG files live in runtime/<id>/.
