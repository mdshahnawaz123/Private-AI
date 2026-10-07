import unittest
from services.model_admission import ModelAdmission,ModelBusyError

class ModelAdmissionTests(unittest.TestCase):
    def test_limit_and_idempotent_release(self):
        admission=ModelAdmission(2);first=admission.require();second=admission.require()
        self.assertIsNone(admission.acquire())
        with self.assertRaises(ModelBusyError):admission.require()
        first.release();first.release()
        replacement=admission.require()
        self.assertIsNone(admission.acquire())
        second.release();replacement.release()
        with admission.require():pass

    def test_failure_releases_capacity(self):
        admission=ModelAdmission(1)
        with self.assertRaises(RuntimeError):
            with admission.require():raise RuntimeError('model failure')
        with admission.require():pass
