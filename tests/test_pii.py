from ingestion.pii_filter import mask_pii


def test_mrn_is_masked():
    masked, found = mask_pii("Incident involved MRN 00482913 and requires review.")
    assert "00482913" not in masked
    assert "[MRN]" in masked
    assert "MRN" in found
