import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from pqc_corpus.export.commits import commits
from pqc_corpus.export.issues import issues
from pqc_corpus.export.pull_requests import pull_requests
from pqc_corpus.export.repositories import repositories
from pqc_corpus.paths import PROJECT_ROOT

from fixtures import REPO, author_keys, make_run

SCHEMAS = PROJECT_ROOT / 'schemas'


@unittest.skipUnless(importlib.util.find_spec('jsonschema'), 'jsonschema is not installed')
class SchemaTests(unittest.TestCase):
    def test_exported_records_match_the_published_schemas(self) -> None:
        import jsonschema
        with tempfile.TemporaryDirectory() as temp:
            run, shas = make_run(Path(temp))
            eligibility = {(REPO, sha): (True, False, None) for sha in shas.values()}
            for name, records in (('commits', commits(run, eligibility, author_keys(Path(temp)))), ('issues', issues(run)),
                                  ('pull_requests', pull_requests(run)), ('repositories', repositories(run))):
                schema = json.loads((SCHEMAS / f'{name}.schema.json').read_text())
                validator = jsonschema.Draft202012Validator(schema)
                for record in records:
                    with self.subTest(file=name):
                        self.assertEqual(list(record), schema['required'])
                        errors = [e.message for e in validator.iter_errors(record)]
                        self.assertEqual(errors, [])


if __name__ == '__main__':
    unittest.main()
