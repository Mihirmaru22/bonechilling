"""DICOM read + pipeline tests, using a synthetic .dcm built with pydicom."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np

from bonechiling.core import dicom as dicom_mod
from bonechiling.core.schema import XrayFacts, LabelReading
from bonechiling.pipeline import runner
from test_pipeline import FakeEngine


def _make_dicom(path: Path):
    import pydicom
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = generate_uid()
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)

    ds.PatientName = "RAMESH PATEL"
    ds.PatientID = "DCM12345"
    ds.PatientAge = "071Y"
    ds.PatientSex = "M"
    ds.BodyPartExamined = "FEMUR"
    ds.ViewPosition = "AP"
    ds.StudyDate = "20250314"
    ds.InstitutionName = "TEST HOSPITAL"

    px = (np.linspace(0, 4095, 64 * 64, dtype=np.uint16)).reshape(64, 64)
    ds.Rows, ds.Columns = 64, 64
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = 16
    ds.BitsStored = 12
    ds.HighBit = 11
    ds.PixelRepresentation = 0
    ds.PixelData = px.tobytes()
    ds.save_as(str(path), write_like_original=False)


def test_is_dicom_and_read():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "study.dcm"
        _make_dicom(p)
        assert dicom_mod.is_dicom(p)
        study = dicom_mod.read_dicom(p)
        assert study is not None
        assert study.image.mode == "L" and study.image.size == (64, 64)
        n = study.norm
        assert n["name"] == "RAMESH PATEL", n
        assert n["age"] == "71", n["age"]
        assert n["sex"] == "M"
        assert n["body_part"] == "femur"
        assert n["views"] == ["AP"]
        assert n["study_date"] == "2025-03-14", n["study_date"]
        assert n["patient_id"] == "DCM12345"


def test_pipeline_handles_dicom():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "img.dcm"
        _make_dicom(p)
        facts = XrayFacts(image_type="X-ray", body_part="femur", views=["AP"],
                          label=LabelReading(name="RAMESH PATEL"))
        eng = FakeEngine(facts)
        rec = runner.analyze_image(p, eng)
        assert rec["source"] == "dicom", rec.get("source")
        assert rec["facts"].body_part == "femur"
        assert eng.calls == 1  # engine ran on the rendered pixels
        # tags-vs-VLM name agreement recorded
        assert rec["crosscheck"]["name"]["status"] in ("verified", "vlm_only", "ocr_only")


if __name__ == "__main__":
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("PASS", name); n += 1
    print(f"\n{n} tests passed")
