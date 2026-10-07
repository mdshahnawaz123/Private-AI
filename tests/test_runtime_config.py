import unittest
from config import Settings


class RuntimeConfigTests(unittest.TestCase):
    def test_no_32b_or_arbitrary_models(self):
        for name in ('qwen:32b','qwen2.5:32b','unknown'):
            with self.assertRaises(ValueError): Settings(chat_model=name,_env_file=None)

    def test_cors_both_formats(self):
        for value in ('http://localhost:8090', '["http://localhost:8090"]'):
            self.assertEqual(Settings(cors_origins=value,_env_file=None).cors_origins,['http://localhost:8090'])

if __name__=='__main__': unittest.main()
