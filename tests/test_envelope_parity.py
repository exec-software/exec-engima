"""The Python host's envelope bytes, pinned against the Matrix codec's.

ENI-0003 makes byte-identical envelopes the precondition for porting the host:
identical bytes let either host read a directory the other wrote, so a
half-ported tree stays testable. The Matrix side pins the same golden vectors
in the `enigma.storage.envelope` suite, asserting the exact bytes below. Each
side is an independent witness, so either encoder drifting fails a test here or
there rather than silently producing two spellings of one checkpoint.

The real-state comparison lives in `validation/nil-io`, which runs a Matrix
program against a matching development SDK and compares its envelope with the
bytes this host would write for the same payload.
"""

import hashlib
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("enigma_store_host", ROOT / "scripts" / "store.py")
host = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(host)

# Golden vectors. The Matrix suite asserts byte-for-byte equality with these.
SIMPLE_PAYLOAD = '{"schema":"enigma.state.v1"}'
SIMPLE_DIGEST = "3d1ffca68a95d9ee3e06ad2692fff0f9bb841a8c598f1ee26bf8459aadccdf2a"
SIMPLE_ENVELOPE = (
    '{"format":"enigma.checkpoint.v1","payload":"{\\"schema\\":\\"enigma.state.v1\\"}",'
    '"sha256":"3d1ffca68a95d9ee3e06ad2692fff0f9bb841a8c598f1ee26bf8459aadccdf2a"}'
)


def envelope_bytes(payload):
    """Exactly what Store.commit writes, without touching a filesystem."""
    return host._json_bytes({"format": host.FORMAT, "payload": payload,
                             "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest()})


class EnvelopeParityTests(unittest.TestCase):
    def test_golden_vector_matches_the_bytes_matrix_asserts(self):
        self.assertEqual(SIMPLE_DIGEST, hashlib.sha256(SIMPLE_PAYLOAD.encode()).hexdigest())
        self.assertEqual(envelope_bytes(SIMPLE_PAYLOAD), SIMPLE_ENVELOPE.encode("utf-8"))

    def test_format_identifier_is_the_one_matrix_writes(self):
        self.assertEqual(host.FORMAT, "enigma.checkpoint.v1")

    def test_members_are_alphabetical_so_both_orderings_agree(self):
        # NILData sorts object members; json.dumps preserves insertion order.
        # The two coincide only while these names are in alphabetical order, so
        # a member added out of order is a byte-level divergence, not a style
        # choice. This asserts the property rather than the current spelling.
        members = list(json.loads(envelope_bytes(SIMPLE_PAYLOAD)))
        self.assertEqual(members, sorted(members))
        self.assertEqual(members, ["format", "payload", "sha256"])

    def test_a_json_payload_carries_no_raw_control_byte(self):
        # The other property byte-identity depends on: NILData escapes a
        # control character as \u000a where Python writes \n. A payload is JSON
        # output, and JSON escapes every control character, so neither encoder
        # can be asked to spell one. A payload holding raw control bytes would
        # break parity, so this checks the guarantee at its source.
        awkward = {"quote": '"', "backslash": "\\", "newline": "\n", "tab": "\t",
                   "astral": "é日本🦊", "nested": [{"control": "\x00\x1f"}]}
        payload = host._json_bytes(awkward).decode("utf-8")
        self.assertEqual([b for b in payload.encode("utf-8") if b < 0x20], [])
        # And the envelope that wraps it is equally free of them.
        self.assertEqual([b for b in envelope_bytes(payload) if b < 0x20], [])

    def test_escape_heavy_payload_round_trips_through_the_envelope(self):
        payload = host._json_bytes({"a": '"b\\c\nd\te', "u": "é日本🦊"}).decode("utf-8")
        content = envelope_bytes(payload)
        envelope = host.strict_json(content)
        self.assertEqual(set(envelope), {"format", "payload", "sha256"})
        self.assertEqual(envelope["payload"], payload)
        self.assertEqual(envelope["sha256"],
                         hashlib.sha256(payload.encode("utf-8")).hexdigest())

    def test_the_digest_covers_the_payload_not_the_envelope(self):
        # Recovery recomputes over the payload member alone, so envelope
        # whitespace or member order can never change a stored digest.
        payload = SIMPLE_PAYLOAD
        envelope = host.strict_json(envelope_bytes(payload))
        self.assertEqual(envelope["sha256"],
                         hashlib.sha256(envelope["payload"].encode("utf-8")).hexdigest())
        spaced = json.dumps(envelope, ensure_ascii=False).encode("utf-8")
        self.assertNotEqual(spaced, envelope_bytes(payload))
        self.assertEqual(host.strict_json(spaced)["sha256"], envelope["sha256"])


if __name__ == "__main__":
    unittest.main()
