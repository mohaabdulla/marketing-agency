"""Automated verification suite for LEXNIS Campaign Studio Operating System.

Tests all master implementation requirements:
- Model Registry & Commercial Licensing Gates
- Campaign Command Center (15-stage lifecycle, risks, readiness)
- Local Research Document Vault & Evidence Verification
- Creative Evaluation Layer (channel constraints, brand rules, RTL)
- Local TTS & Music Engines (synthesis & commercial gates)
- Marketing Connectors & Offline Publication ZIP Package
- Tracking UTMs, KPI Normalization & CSV Analytics Import
- Client Review Portal & Billing Calculations
- Root and Agency REST API endpoints
"""
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server import app
from agency.model_registry import registry as model_registry, CommercialStatus, TaskType
from agency.orchestrator import orchestrator, CampaignStage, StageStatus, STAGE_ORDER
from agency.documents import document_vault
from agency.evidence import evidence_engine, EvidenceType, ReviewState
from agency.creative_eval import evaluator
from agency.tts import tts_engine
from agency.music import music_engine
from agency.connectors import connector_registry, package_builder
from agency.tracking import UTMParameters, calculate_canonical_kpis, parse_analytics_csv
from agency.portal import create_client_review_link, get_review_portal_data, submit_review_decision, generate_billing_summary
from agency.services import service


class AgencyMasterSuiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        # Create an isolated test client and campaign in the database
        res = cls.client.post("/api/agency/clients", json={
            "name": "Acme Robotics Enterprise",
            "industry": "Industrial Robotics",
            "website": "https://acmerobotics.com",
            "description": "Autonomous manufacturing automation",
            "markets": ["Global", "US"],
            "languages": ["en", "ar"],
            "timezone": "UTC",
            "status": "active"
        })
        assert res.status_code == 201, f"Setup client failed: {res.text}"
        cls.client_id = res.json()["id"]

        # Create test campaign adhering to strict campaigns schema
        camp_res = cls.client.post(f"/api/agency/clients/{cls.client_id}/records/campaigns", json={
            "name": "RoboFleet Autonomous Launch 2026",
            "data": {
                "status": "creative",
                "objective": "Enterprise B2B Lead Generation",
                "primary_kpi": "CPA",
                "start_date": "2026-11-01",
                "end_date": "2026-12-01",
                "budget": 25000.0,
                "currency": "USD",
                "markets": ["Global", "US"],
                "languages": ["en", "ar"],
                "notes": "RoboFleet Autonomous Launch 2026"
            }
        })
        assert camp_res.status_code == 201, f"Setup campaign failed: {camp_res.text}"
        cls.campaign_id = camp_res.json()["id"]

    # 1. MODEL REGISTRY & LICENSING GATES
    def test_01_model_registry_manifests_and_capabilities(self):
        models = model_registry.list_models()
        self.assertGreaterEqual(len(models), 15)

        # Check task coverage
        tasks = {m["task"] for m in models}
        self.assertIn("text", tasks)
        self.assertIn("image", tasks)
        self.assertIn("video", tasks)
        self.assertIn("audio_asr", tasks)
        self.assertIn("audio_tts", tasks)
        self.assertIn("audio_music", tasks)

        # Capabilities probe
        caps = model_registry.probe_system_capabilities()
        self.assertIn("cpu_count", caps)
        self.assertIn("ram_total_gb", caps)
        self.assertIn("cuda_available", caps)
        self.assertIn("total_registered_models", caps)

    def test_02_commercial_licensing_gates_strict_enforcement(self):
        # Commercial mode: Apache 2.0 allowed
        flux_gate = model_registry.check_license_gate("flux.1-schnell", "commercial")
        self.assertTrue(flux_gate["allowed"])
        self.assertEqual(flux_gate["status"], "COMMERCIAL_ALLOWED")

        # Commercial mode: CPML Coqui XTTS-v2 BLOCKED
        xtts_gate = model_registry.check_license_gate("coqui-xtts-v2", "commercial")
        self.assertFalse(xtts_gate["allowed"])
        self.assertEqual(xtts_gate["status"], "NON_COMMERCIAL")
        self.assertIn("PROHIBITS", xtts_gate["reason"])

        # Commercial mode: CC-BY-NC MusicGen BLOCKED
        musicgen_gate = model_registry.check_license_gate("musicgen-small", "commercial")
        self.assertFalse(musicgen_gate["allowed"])
        self.assertEqual(musicgen_gate["status"], "NON_COMMERCIAL")

        # Conditional license triggers warning
        llama_gate = model_registry.check_license_gate("llama-3.1-8b-instruct", "commercial")
        self.assertTrue(llama_gate["allowed"])
        self.assertGreater(len(llama_gate["warnings"]), 0)

    # 2. CAMPAIGN COMMAND CENTER
    def test_03_campaign_command_center_stages_and_risks(self):
        data = orchestrator.get_campaign_command_center(self.client_id, self.campaign_id)
        self.assertEqual(data["campaign"]["name"], "RoboFleet Autonomous Launch 2026")
        self.assertEqual(len(data["stages"]), 15)
        self.assertEqual(data["stages"][0]["stage"], "INTAKE")
        self.assertEqual(data["stages"][-1]["stage"], "COMPLETE")

        # Initial campaign lacks approved brief and evidence -> should report risks
        risks = data["risks"]
        risk_codes = {r["code"] for r in risks}
        self.assertIn("MISSING_BRIEF", risk_codes)
        self.assertEqual(data["readiness"]["status"], "BLOCKED")

    def test_04_campaign_command_center_stage_advance(self):
        adv = orchestrator.advance_stage(self.client_id, self.campaign_id, "CONCEPT")
        self.assertTrue(adv["success"])
        self.assertEqual(adv["current_stage"], "CONCEPT")

        # Check updated command center state
        data = orchestrator.get_campaign_command_center(self.client_id, self.campaign_id)
        self.assertEqual(data["campaign"]["current_stage"], "CONCEPT")

    # 3. RESEARCH DOCUMENT VAULT & EVIDENCE
    def test_05_document_vault_ingestion_and_chunking(self):
        doc_content = (
            "LEXNIS Industrial Automation Whitepaper 2026.\n\n"
            "RoboFleet demonstrates a 99.98% uptime across 45 manufacturing deployments. "
            "Autonomous path planning reduces battery cycle degradation by 34% compared to legacy AGVs.\n\n"
            "Section 2: Safety and Verification.\n"
            "Full fail-safe braking complies with ISO-13849 Category 4 performance level e."
        ).encode("utf-8")

        res = document_vault.ingest_bytes(
            client_id=self.client_id,
            filename="robofleet_whitepaper.txt",
            data=doc_content,
            mime_type="text/plain",
        )
        self.assertEqual(res["metadata"]["extraction_status"], "SUCCESS")
        self.assertGreater(len(res["chunks"]), 0)
        chunk_id = res["chunks"][0]["chunk_id"]

        # Search chunks
        search_res = document_vault.search_chunks(self.client_id, "uptime")
        self.assertGreater(len(search_res), 0)
        self.assertEqual(search_res[0]["chunk_id"], chunk_id)

    def test_06_evidence_citation_and_claim_verification(self):
        docs = document_vault.list_documents(self.client_id)
        self.assertGreater(len(docs), 0)
        doc = document_vault.get_document(self.client_id, docs[0]["document_id"])
        chunk_id = doc["chunks"][0]["chunk_id"]

        # Register verified evidence
        ev = evidence_engine.register_evidence(
            client_id=self.client_id,
            claim_text="99.98% fleet uptime verified in manufacturing",
            chunk_ids=[chunk_id],
            evidence_type=EvidenceType.DOCUMENT_EXCERPT,
            notes="Extracted from official whitepaper section 1"
        )
        self.assertEqual(ev["data"]["state"], "verified_source")

        # Invalid chunk ID must fail validation
        with self.assertRaises(ValueError):
            evidence_engine.register_evidence(
                client_id=self.client_id,
                claim_text="Fake metric",
                chunk_ids=["non_existent_chunk_999"]
            )

    # 4. CREATIVE EVALUATION LAYER
    def test_07_creative_evaluation_pass_and_hard_rules(self):
        # Valid B2B copy
        res = evaluator.evaluate_copy(
            headline="Accelerate Industrial Throughput with Autonomous AI",
            body="Eliminate costly line stoppages with RoboFleet vision intelligence. Apply for a private engineering demo at lexnis.com",
            channel="linkedin",
            language="en"
        )
        self.assertTrue(res.passed)
        self.assertEqual(res.score, 100)

        # Copy violating character limits and containing prohibited terms
        res_fail = evaluator.evaluate_copy(
            headline="A" * 150,  # Exceeds LinkedIn 120 max
            body="Guaranteed 100% risk-free miracle cure for factory lines.",
            channel="linkedin",
            language="en"
        )
        self.assertFalse(res_fail.passed)
        self.assertIn("Headline length", res_fail.hard_failures[0])
        self.assertTrue(any("Prohibited term" in h for h in res_fail.hard_failures))

    # 5. LOCAL TTS & MUSIC STUDIO
    def test_08_tts_synthesis_and_gating(self):
        # List commercial voices
        voices = tts_engine.list_voices(commercial_only=True)
        self.assertTrue(all(v["commercial_allowed"] for v in voices))

        # Synthesize voiceover
        res = tts_engine.generate_voiceover(
            text="Autonomous vision intelligence delivered with zero paid cloud APIs.",
            voice_id="af_sarah",
            speed=1.0,
            commercial_mode=True
        )
        self.assertTrue(res["success"])
        self.assertTrue(Path(res["file_path"]).exists())
        self.assertGreater(res["duration_seconds"], 0)

        # Blocked non-commercial XTTS
        with self.assertRaises(PermissionError):
            tts_engine.generate_voiceover(
                text="Commercial post voice",
                voice_id="xtts_noncommercial",
                commercial_mode=True
            )

    def test_09_music_synthesis_and_gating(self):
        res = music_engine.generate_soundtrack(
            prompt="Inspiring corporate tech background",
            genre="Corporate Ambient",
            duration_seconds=3.0,
            commercial_mode=True
        )
        self.assertTrue(res["success"])
        self.assertTrue(Path(res["track"]["file_path"]).exists())
        self.assertEqual(res["track"]["license_id"], "Apache-2.0")

        # Blocked non-commercial MusicGen
        with self.assertRaises(PermissionError):
            music_engine.generate_soundtrack(
                prompt="Commercial track",
                model_id="musicgen-small",
                commercial_mode=True
            )

    # 6. CONNECTORS & PUBLICATION PACKAGE
    def test_10_marketing_connectors_and_offline_package(self):
        conns = connector_registry.list_connectors()
        cids = [c["connector_id"] for c in conns]
        self.assertIn("linkedin", cids)
        self.assertIn("youtube", cids)
        self.assertIn("meta", cids)
        self.assertIn("google_ads", cids)

        # Build offline ZIP package
        zip_bytes, filename = package_builder.build_package(self.client_id, self.campaign_id)
        self.assertTrue(filename.endswith(".zip"))
        self.assertGreater(len(zip_bytes), 500)

        # Inspect ZIP contents
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
            self.assertIn("manifest.json", names)
            self.assertIn("README.md", names)
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            self.assertEqual(manifest["campaign_id"], self.campaign_id)
            self.assertIn("utm_tracking", manifest)

    # 7. TRACKING & ANALYTICS
    def test_11_utm_builder_and_kpi_normalization(self):
        utm = UTMParameters(
            source="linkedin",
            medium="sponsored_update",
            campaign="robofleet_launch_2026",
            content="variant_a_video",
            term="industrial_ai"
        )
        built_url = utm.build_url("https://lexnis.com/enterprise")
        self.assertIn("utm_source=linkedin", built_url)
        self.assertIn("utm_campaign=robofleet_launch_2026", built_url)

        # Test canonical KPI calculations
        kpis = calculate_canonical_kpis(
            impressions=10000,
            clicks=250,
            spend=500.0,
            conversions=25,
            revenue=2500.0
        )
        self.assertEqual(kpis["ctr_percent"], 2.5)   # 250 / 10000 * 100
        self.assertEqual(kpis["cpm"], 50.0)          # 500 / 10000 * 1000
        self.assertEqual(kpis["cpc"], 2.0)           # 500 / 250
        self.assertEqual(kpis["cpa"], 20.0)          # 500 / 25
        self.assertEqual(kpis["cvr_percent"], 10.0)  # 25 / 250 * 100
        self.assertEqual(kpis["roas"], 5.0)          # 2500 / 500
        # Undefined ratios are reported as undefined, not as a misleading zero.
        empty = calculate_canonical_kpis(impressions=1000, clicks=0, spend=0.0)
        self.assertEqual((empty["ctr_percent"], empty["cpc"], empty["roas"]), (0.0, None, None))
        tagged = UTMParameters(source="LinkedIn", medium="Paid Social", campaign="Spring Sale", id="q2-042", source_platform="Google Ads")
        url = tagged.build_url("https://lexnis.com/p?ref=a&utm_source=old")
        self.assertEqual(url, "https://lexnis.com/p?ref=a&utm_source=linkedin&utm_medium=paid-social&utm_campaign=spring-sale"
                              "&utm_id=q2-042&utm_source_platform=google-ads")
        with self.assertRaisesRegex(ValueError, "email address"):
            UTMParameters(source="newsletter", medium="email", campaign="x", content="jane@example.com").build_url("https://lexnis.com")
        with self.assertRaisesRegex(ValueError, "absolute http"):
            tagged.build_url("lexnis.com/p")

    def test_12_csv_analytics_import(self):
        sample_csv = (
            "date,channel,campaign,impressions,clicks,spend,conversions,revenue\n"
            "2026-11-01,linkedin,RoboFleet,5000,100,200.0,10,1000.0\n"
            "2026-11-02,meta,RoboFleet,8000,160,240.0,12,1200.0\n"
        )
        parsed = parse_analytics_csv(sample_csv)
        self.assertEqual(parsed["rows_count"], 2)
        self.assertEqual(parsed["summary"]["impressions"], 13000)
        self.assertEqual(parsed["summary"]["clicks"], 260)
        self.assertEqual(parsed["summary"]["spend"], 440.0)
        self.assertAlmostEqual(parsed["summary"]["roas"], 5.0, places=1)
        # Real exports: header case, thousands separators, currency symbols, blank optional cells.
        exported = parse_analytics_csv('Date,Channel,Impressions,Clicks,Spend,Conversions\n'
                                       '2026-11-03,meta,"1,200",30,"$45.50",\n')
        self.assertEqual((exported["summary"]["impressions"], exported["summary"]["spend"], exported["summary"]["cpa"]), (1200, 45.5, None))
        with self.assertRaisesRegex(ValueError, "Line 2: clicks"):
            parse_analytics_csv("date,channel,impressions,clicks,spend\n2026-11-01,meta,100,-3,5\n")

    # 8. CLIENT REVIEW PORTAL & BILLING
    def test_13_client_review_portal_and_billing(self):
        # Create expiring link
        link = create_client_review_link(
            client_id=self.client_id,
            campaign_id=self.campaign_id,
            asset_ids=[],
            expires_in_days=3
        )
        token = link["token"]
        self.assertTrue(token)

        # Access portal
        portal_data = get_review_portal_data(token)
        self.assertEqual(portal_data["campaign_name"], "RoboFleet Autonomous Launch 2026")

        # Submit decision
        dec = submit_review_decision(
            token=token,
            reviewer_name="Dr. Elena Vance (VP Engineering)",
            decision="APPROVED",
            comments="Approved for Q4 enterprise rollout."
        )
        self.assertTrue(dec["success"])
        self.assertEqual(dec["decision"], "APPROVED")

        # The link survives a restart (stored as a digest only) and binds decisions to the shared version.
        import agency.portal as portal
        store = portal._store_path().read_text(encoding="utf-8")
        self.assertNotIn(token, store)
        self.assertIn(portal._digest(token), store)
        with self.assertRaises(ValueError):
            create_client_review_link(self.client_id, self.campaign_id, [], expires_in_days=365)
        with self.assertRaises(ValueError):
            submit_review_decision(token, reviewer_name="Elena", decision="CHANGES_REQUESTED", comments="")
        portal.revoke_review_link(self.client_id, token)
        from agency.database import Conflict
        with self.assertRaises(Conflict):           # a revoked link can no longer approve
            submit_review_decision(token, reviewer_name="Elena", decision="APPROVED")
        with self.assertRaises(Conflict):
            get_review_portal_data(token)

        # Billing is an editable estimate in the campaign's currency, with the agency country's VAT rate.
        billing = generate_billing_summary(self.client_id, self.campaign_id)
        self.assertEqual(billing["document_type"], "ESTIMATE")
        self.assertGreater(billing["total"], 0)
        from agency.services import service
        self.assertEqual(billing["currency"], service.get(self.client_id, self.campaign_id, "campaigns")["data"]["currency"])
        self.assertEqual((billing["vat_country"], billing["vat_rate"]), ("BH", 0.10))
        self.assertAlmostEqual(billing["tax"], billing["subtotal"] * 0.10, places=3)
        self.assertGreater(len(billing["line_items"]), 0)

    def test_13b_review_revocation_and_utm_over_http(self):
        prefix = "/api/agency"
        link = self.client.post(f"{prefix}/clients/{self.client_id}/review-links",
                                json={"campaign_id": self.campaign_id, "asset_ids": [], "expires_in_days": 2}).json()
        self.assertEqual(self.client.get(f"{prefix}/review-links/{link['token']}").status_code, 200)
        revoked = self.client.post(f"{prefix}/clients/{self.client_id}/review-links/revoke", json={"token": link["token"]})
        self.assertEqual((revoked.status_code, revoked.json()["status"]), (200, "REVOKED"))
        self.assertEqual(self.client.get(f"{prefix}/review-links/{link['token']}").status_code, 409)
        built = self.client.post(f"{prefix}/tracking/build-utm", json={"base_url": "https://lexnis.com/p", "source": "LinkedIn",
                                                                       "medium": "Paid Social", "campaign": "Q4 Launch", "id": "q4-001"}).json()
        self.assertEqual(built["url"], "https://lexnis.com/p?utm_source=linkedin&utm_medium=paid-social&utm_campaign=q4-launch&utm_id=q4-001")
        self.assertTrue(built["warnings"])
        refused = self.client.post(f"{prefix}/tracking/build-utm", json={"base_url": "https://lexnis.com", "source": "x", "medium": "email",
                                                                         "campaign": "y", "content": "jane@example.com"})
        self.assertEqual(refused.status_code, 400)

    # 9. REST API ENDPOINTS INTEGRATION
    def test_14_fastapi_rest_endpoints(self):
        # System capabilities
        r = self.client.get("/api/system/capabilities")
        self.assertEqual(r.status_code, 200)
        self.assertIn("cpu_count", r.json())

        # Baseline security headers on pages, APIs and errors; a route's own stricter policy is kept.
        for response in (self.client.get("/"), r, self.client.get("/api/agency/review-links/" + "x" * 30)):
            self.assertEqual(response.headers["x-content-type-options"], "nosniff")
            self.assertEqual(response.headers["x-frame-options"], "SAMEORIGIN")
            self.assertEqual(response.headers["referrer-policy"], "same-origin")
            self.assertIn("frame-ancestors 'self'", response.headers["content-security-policy"])
            self.assertIn("camera=()", response.headers["permissions-policy"])
            self.assertNotIn("strict-transport-security", response.headers)       # plain HTTP: no HSTS

        # Invalid requests answer 422 without echoing the rejected body, even when it is binary.
        r = self.client.post("/api/brands", files={"file": ("f.csv", b"\xff\xfe\x00secret-body", "text/csv")}, data={"name": "x"})
        self.assertEqual(r.status_code, 422)
        self.assertNotIn("secret-body", r.text)
        r = self.client.post("/api/agency/tracking/build-utm", json={"base_url": "https://x.example", "source": 5, "private": "secret-body"})
        self.assertEqual(r.status_code, 422)
        self.assertNotIn("secret-body", r.text)
        self.assertTrue(all({"type", "loc", "msg"} == set(e) for e in r.json()["detail"]))
        # Studio routes refuse oversized bodies before reading them.
        r = self.client.post("/api/brands", content=b"{}", headers={"content-type": "application/json", "content-length": str(65 * 1024**2)})
        self.assertEqual(r.status_code, 413)
        # Uploads must be real images, and the slot (part of the stored file name) cannot leave the uploads folder.
        junk = ("photo.png", b"print('not an image')", "image/png")
        r = self.client.post("/api/upload-visual", files={"file": junk}, data={"slot": "logo"})
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/upload-visual", files={"file": junk}, data={"slot": "../escape"})
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "Invalid visual slot"))
        r = self.client.post("/api/template-swap", files={"template_file": junk, "subject_file": junk})
        self.assertEqual(r.status_code, 400)
        self.assertNotIn("OpenCV", r.text)

        # Models catalog
        r = self.client.get("/api/agency/models")
        self.assertEqual(r.status_code, 200)
        self.assertGreater(len(r.json()), 10)

        # Command Center endpoint
        r = self.client.get(f"/api/agency/clients/{self.client_id}/campaigns/{self.campaign_id}/command-center")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["campaign"]["name"], "RoboFleet Autonomous Launch 2026")

        # Readiness endpoint
        r = self.client.get(f"/api/agency/clients/{self.client_id}/campaigns/{self.campaign_id}/readiness")
        self.assertEqual(r.status_code, 200)
        self.assertIn("status", r.json())

        # Creative eval endpoint
        r = self.client.post("/api/agency/creative-eval/check", json={
            "headline": "Scalable Fleet Vision",
            "body": "Deploy machine learning at the edge. Visit lexnis.com",
            "channel": "linkedin",
            "language": "en"
        })
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["passed"])

        # Offline publication package export endpoint
        r = self.client.post(f"/api/agency/clients/{self.client_id}/campaigns/{self.campaign_id}/export-package")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "application/zip")


if __name__ == "__main__":
    unittest.main()
