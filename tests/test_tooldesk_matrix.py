"""
Tests for ToolDesk Capability Matrix & DPAPI Local Credential Vault.
Verifies the craft-ai-integrations architectural synthesis in Expo Design AI.
"""
import unittest
from core.tooldesk import ToolDesk, ToolPrerequisites, get_tooldesk
from core.model_registry import ModelConfig, ModelRole, get_registry
from core.credential_vault import get_vault, LocalCredentialVault
from agents.tools import get_registry as get_tool_registry, ToolPermission, ToolDefinition


class TestToolDeskMatrix(unittest.TestCase):

    def setUp(self):
        self.tooldesk = get_tooldesk()
        self.tool_reg = get_tool_registry()
        self.model_reg = get_registry()

    def test_prerequisites_serialization(self):
        prereq = ToolPrerequisites(
            required_capabilities=["chat", "reasoning"],
            min_context_tokens=16384,
            input_modalities=["text", "pdf"],
            output_modalities=["text"],
            recommended_role="REASONING_LLM",
        )
        d = prereq.to_dict()
        self.assertEqual(d["min_context_tokens"], 16384)
        self.assertIn("reasoning", d["required_capabilities"])
        self.assertIn("pdf", d["input_modalities"])
        self.assertEqual(d["recommended_role"], "REASONING_LLM")

    def test_audit_matrix_summary(self):
        audit = self.tooldesk.audit_matrix()
        self.assertIn("summary", audit)
        self.assertIn("matrix", audit)

        summary = audit["summary"]
        self.assertGreaterEqual(summary["total_tools"], 14)
        self.assertGreaterEqual(summary["total_models"], 5)
        self.assertGreaterEqual(summary["deterministic_tools"], 3)
        self.assertEqual(summary["coverage_percentage"], 100.0)

    def test_deterministic_tools_bypass_models(self):
        # calculate and run_rule are deterministic tools
        res_calc = self.tooldesk.resolve_model_for_tool("calculate")
        self.assertEqual(res_calc["status"], "DETERMINISTIC_ONLY")
        self.assertTrue(res_calc["deterministic"])
        self.assertIsNone(res_calc["selected_model"])

        res_rule = self.tooldesk.resolve_model_for_tool("run_rule")
        self.assertEqual(res_rule["status"], "DETERMINISTIC_ONLY")
        self.assertTrue(res_rule["deterministic"])

    def test_complex_tools_resolve_reasoning_llm(self):
        res_doc = self.tooldesk.resolve_model_for_tool("read_document")
        self.assertIn(res_doc["status"], ("READY", "FALLBACK_APPLIED"))
        self.assertFalse(res_doc["deterministic"])
        self.assertIn("qwen", res_doc["selected_model"].lower())
        self.assertGreaterEqual(res_doc["token_headroom"], 0)

        res_cad = self.tooldesk.resolve_model_for_tool("cad_draft")
        self.assertIn(res_cad["status"], ("READY", "FALLBACK_APPLIED"))
        self.assertFalse(res_cad["deterministic"])

    def test_insufficient_context_rejection(self):
        # Create a mock small model with small context
        small_model = ModelConfig(
            role="MOCK_TINY",
            name="tiny:0.5b",
            context_length=2048,
            capabilities=["chat", "reasoning"],
            priority=10,
        )
        eval_res = self.tooldesk.check_model_support("read_document", small_model)
        self.assertFalse(eval_res["supported"])
        self.assertLess(eval_res["token_headroom"], 0)
        self.assertTrue(any("Insufficient context window" in r for r in eval_res["reasons"]))

    def test_missing_capability_rejection(self):
        chat_only_model = ModelConfig(
            role="MOCK_CHAT_ONLY",
            name="chat-only:1b",
            context_length=32768,
            capabilities=["chat"],  # missing "structured_outputs"
            priority=10,
        )
        eval_res = self.tooldesk.check_model_support("cad_draft", chat_only_model)
        self.assertFalse(eval_res["supported"])
        self.assertIn("structured_outputs", eval_res["missing_capabilities"])

    def test_fallback_resolution(self):
        # When requesting an incapable or missing model role, fallback must succeed
        res = self.tooldesk.resolve_model_for_tool("cad_inspect", preferred_role="NON_EXISTENT_ROLE")
        self.assertIn(res["status"], ("READY", "FALLBACK_APPLIED"))
        self.assertIsNotNone(res["selected_model"])


class TestLocalCredentialVault(unittest.TestCase):

    def setUp(self):
        self.vault = get_vault()

    def test_dpapi_status(self):
        status = self.vault.get_status()
        self.assertTrue(status["offline_only"])
        self.assertIn(".credential_vault.enc", status["vault_path"])
        self.assertIsInstance(status["keys"], list)

    def test_store_and_retrieve_secret(self):
        key = "comfyui_token_test"
        secret = "secret_auth_token_987654321_flux"

        # Store secret
        ok = self.vault.store_secret(key, secret)
        self.assertTrue(ok)
        self.assertTrue(self.vault.has_secret(key))

        # Retrieve secret
        retrieved = self.vault.get_secret(key)
        self.assertEqual(retrieved, secret)

        # List keys
        keys = self.vault.list_keys()
        self.assertIn(key, keys)

        # Cleanup
        deleted = self.vault.delete_secret(key)
        self.assertTrue(deleted)
        self.assertFalse(self.vault.has_secret(key))
        self.assertIsNone(self.vault.get_secret(key))


if __name__ == "__main__":
    unittest.main()
