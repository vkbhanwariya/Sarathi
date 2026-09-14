"""Unit and integration tests for Translation engine hardware device binding."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    CanonicalDocument,
    DeviceType,
    ExecutionBinding,
    ExecutionContext,
    InputRef,
    PageData,
    Request,
)
from sarathi.shakti.translation.capability import TranslationCapability
from sarathi.shakti.translation.engine import CTranslate2TranslationEngine
from sarathi.shakti.translation.models import (
    Language,
    TranslationDirection,
    TranslationResult,
)
from sarathi.shakti.translation.plugin import CAPABILITY_DECLARATION as TRANSLATION_DECL
from sarathi.yantra import DeviceInfo, DeviceInventory, Yantra

try:
    import ctranslate2

    _has_ctranslate2 = hasattr(ctranslate2, "Translator")
except ImportError:
    _has_ctranslate2 = False

try:
    import sentencepiece  # noqa: F401

    _has_sentencepiece = True
except ImportError:
    _has_sentencepiece = False

pytestmark = pytest.mark.skipif(
    not (_has_ctranslate2 and _has_sentencepiece),
    reason="ctranslate2.Translator or sentencepiece not available",
)


class TestTranslationDeviceBinding:
    def test_translation_engine_uses_cuda_when_available(self, tmp_path) -> None:
        models_dir = tmp_path / "models" / "hi-en"
        models_dir.mkdir(parents=True)
        (models_dir / "spm.model").write_bytes(b"dummy")
        manifest_file = tmp_path / "manifest.json"
        manifest_file.write_text('{"models": {"hi-en": {"version": "1.0"}}}', encoding="utf-8")

        mock_translator = MagicMock()
        mock_hypothesis = MagicMock()
        mock_hypothesis.hypotheses = [["translated", "sentence"]]
        mock_translator.translate_batch.return_value = [mock_hypothesis]

        mock_spm = MagicMock()
        mock_spm.encode_as_pieces.return_value = ["encoded"]
        mock_spm.decode_pieces.return_value = "Hello World"

        binding_cuda = ExecutionBinding(
            device_id="gpu-0",
            device_type=DeviceType.GPU,
            backend="ctranslate2",
            backend_device_id="cuda",
        )

        with (
            patch("ctranslate2.Translator", return_value=mock_translator) as mock_trans_cls,
            patch("ctranslate2.get_cuda_device_count", return_value=1),
            patch("sentencepiece.SentencePieceProcessor", return_value=mock_spm),
        ):
            engine = CTranslate2TranslationEngine(data_root=tmp_path)
            res = engine.translate("नमस्ते", direction=TranslationDirection.HI_TO_EN, execution_binding=binding_cuda)

            assert res.translated_text == "Hello World"
            assert res.metadata["device"] == "cuda"
            assert res.metadata["backend"] == "ctranslate2"
            mock_trans_cls.assert_called_once_with(
                str(models_dir), device="cuda", device_index=0, inter_threads=1, intra_threads=0
            )

    def test_translation_engine_falls_back_to_cpu_when_cuda_unavailable(self, tmp_path) -> None:
        models_dir = tmp_path / "models" / "hi-en"
        models_dir.mkdir(parents=True)
        (models_dir / "spm.model").write_bytes(b"dummy")
        manifest_file = tmp_path / "manifest.json"
        manifest_file.write_text('{"models": {"hi-en": {"version": "1.0"}}}', encoding="utf-8")

        mock_translator = MagicMock()
        mock_hypothesis = MagicMock()
        mock_hypothesis.hypotheses = [["translated"]]
        mock_translator.translate_batch.return_value = [mock_hypothesis]

        mock_spm = MagicMock()
        mock_spm.encode_as_pieces.return_value = ["encoded"]
        mock_spm.decode_pieces.return_value = "Hello"

        binding_cuda = ExecutionBinding(
            device_id="gpu-0",
            device_type=DeviceType.GPU,
            backend="ctranslate2",
            backend_device_id="cuda",
        )

        with (
            patch("ctranslate2.Translator", return_value=mock_translator) as mock_trans_cls,
            patch("ctranslate2.get_cuda_device_count", return_value=0),
            patch("sentencepiece.SentencePieceProcessor", return_value=mock_spm),
        ):
            engine = CTranslate2TranslationEngine(data_root=tmp_path)
            res = engine.translate("नमस्ते", direction=TranslationDirection.HI_TO_EN, execution_binding=binding_cuda)

            assert res.translated_text == "Hello"
            assert res.metadata["device"] == "cpu"
            mock_trans_cls.assert_called_once_with(
                str(models_dir), device="cpu", device_index=0, inter_threads=1, intra_threads=1
            )

    def test_translation_engine_raises_on_gpu_init_failure_without_cpu_fallback(self, tmp_path) -> None:
        models_dir = tmp_path / "models" / "hi-en"
        models_dir.mkdir(parents=True)
        (models_dir / "spm.model").write_bytes(b"dummy")
        manifest_file = tmp_path / "manifest.json"
        manifest_file.write_text('{"models": {"hi-en": {"version": "1.0"}}}', encoding="utf-8")

        mock_spm = MagicMock()
        mock_spm.encode_as_pieces.return_value = ["encoded"]
        mock_spm.decode_pieces.return_value = "Hello"

        binding_cuda = ExecutionBinding(
            device_id="gpu-0",
            device_type=DeviceType.GPU,
            backend="ctranslate2",
            backend_device_id="cuda",
        )

        with (
            patch("ctranslate2.Translator", side_effect=RuntimeError("CUDA initialization failed")),
            patch("ctranslate2.get_cuda_device_count", return_value=1),
            patch("sentencepiece.SentencePieceProcessor", return_value=mock_spm),
        ):
            engine = CTranslate2TranslationEngine(data_root=tmp_path)
            with pytest.raises(DoshError) as exc_info:
                engine.translate("नमस्ते", direction=TranslationDirection.HI_TO_EN, execution_binding=binding_cuda)
            assert exc_info.value.code == FailureCode.EXECUTION_FAILED
            assert "Failed to initialize translation model" in exc_info.value.message

    def test_translation_capability_records_device_in_provenance(self) -> None:
        mock_engine = MagicMock(spec=CTranslate2TranslationEngine)
        mock_engine.translate.return_value = TranslationResult(
            translated_text="Translated Content",
            source_language=Language.HINDI,
            target_language=Language.ENGLISH,
            direction=TranslationDirection.HI_TO_EN,
            protected_spans_count=0,
            metadata={"device": "cuda", "backend": "ctranslate2"},
        )

        cap = TranslationCapability(engine=mock_engine)

        binding = ExecutionBinding(
            device_id="gpu-0",
            device_type=DeviceType.GPU,
            backend="ctranslate2",
            backend_device_id="cuda",
        )
        ctx = ExecutionContext(
            run_id="r1",
            request_id="req-trans",
            trace_id="t1",
            span_id="s1",
            execution_binding=binding,
        )
        req = Request(
            request_id="req-trans",
            requirement="translate",
            inputs=(InputRef(input_id="in-1", source_path="dummy.txt", display_name="dummy.txt", size_bytes=10, media_type="text/plain"),),
        )
        prior_doc = CanonicalDocument(
            document_id="doc-1",
            source_input_id="in-1",
            text="कुछ पाठ",
            pages=(PageData(page_number=1, text="कुछ पाठ"),),
        )
        from sarathi.sankalpa import Result
        prior_res = Result(
            data=prior_doc,
        )

        result = cap.execute(req, ctx, prior_result=prior_res)
        assert result.data is not None
        assert len(result.provenance) >= 1
        prov = result.provenance[0]
        assert prov.evidence["device"] == "cuda"
        assert prov.evidence["backend"] == "ctranslate2"
        mock_engine.translate.assert_called_once()
        call_kwargs = mock_engine.translate.call_args[1]
        assert call_kwargs["execution_binding"] == binding

    def test_translation_preferred_device_is_gpu_with_cpu_fallback(self) -> None:
        """Verify translation capability prioritizes GPU over CPU and spills over when GPU is full."""
        assert TRANSLATION_DECL.device_requirement.preferred_devices == (DeviceType.GPU,)
        assert TRANSLATION_DECL.device_requirement.supported_devices == (DeviceType.GPU, DeviceType.CPU)

        inventory = DeviceInventory([
            DeviceInfo(device_id="gpu-0", device_type=DeviceType.GPU, capacity=1),
            DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=4),
        ])
        yantra = Yantra(inventory)

        # First allocation receives preferred GPU slot
        alloc1 = yantra.allocate(TRANSLATION_DECL.device_requirement)
        try:
            assert alloc1.device_type == DeviceType.GPU
            assert alloc1.device_id == "gpu-0"
            assert alloc1.is_spillover is False

            # When GPU slot is full, allocation spills over to CPU
            alloc2 = yantra.allocate(TRANSLATION_DECL.device_requirement)
            try:
                assert alloc2.device_type == DeviceType.CPU
                assert alloc2.device_id == "cpu-0"
                assert alloc2.is_spillover is True
            finally:
                yantra.release(alloc2)
        finally:
            yantra.release(alloc1)
