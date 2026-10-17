"""Stable Chromium extension identity (fixed manifest `key` → deterministic extension id)."""

from __future__ import annotations

# Generated once; do not rotate without updating native host allowed_origins everywhere.
MANIFEST_KEY_B64 = (
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAzkcndIAKUjUhr3pST+H6l007k/Mn7YWm2Sxz09NJqp8oBnwu5y9an1LEq"
    "q/EAaygHxWwhG+MNuBgbSt2UyG+lqC+zt+KAAhkQnPV479KlalH2cWHX3EnB901r70hZAyq+w0PuCt3AM/vKgxIPZOWTTx26g4Hc9"
    "hv0HXL/KWki4umut0GkbbxltR6sG01RgRkk+17ryhjyoTtPMsCfz0aJh3g8q4x5Muz6Xa6fhVgj35v3V9TDlVqHJZR7B+pHWlpt"
    "331lyhjjsyB6BdKO+BFg7SPrZnhuq0pstD04fZQvsPoJZf6Wfb2S2HdqQXqyTvVCN6S+zLBlidm/yJAtwmAGaQIDAQAB"
)
EXTENSION_ID = "apkfeonhbjpaplapnadecelcljpknplc"
ALLOWED_ORIGIN = f"chrome-extension://{EXTENSION_ID}/"
