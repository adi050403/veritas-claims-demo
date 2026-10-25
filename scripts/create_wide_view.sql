-- report_wide VIEW sketch (BigQuery / SQLite-compatible idea).
-- Physical store remains long/narrow; analytics consumers can pivot defined tests.
-- Example for a small set of canonical tests:

-- BigQuery:
CREATE OR REPLACE VIEW `veritas_claims_demo.report_wide` AS
SELECT
  document_id,
  clinic_id,
  patient_name,
  gender,
  age,
  MAX(IF(test_name_canonical = 'HAEMOGLOBIN', result_value, NULL)) AS Hemoglobin,
  MAX(IF(test_name_canonical = 'HAEMOGLOBIN', result_value, NULL)) AS Hemoglobin_Result,
  MAX(IF(test_name_canonical = 'HAEMOGLOBIN', range_text, NULL)) AS Hemoglobin_Range,
  MAX(IF(test_name_canonical = 'HAEMOGLOBIN', unit_canonical, NULL)) AS Hemoglobin_Unit,
  MAX(IF(test_name_canonical = 'HAEMOGLOBIN', test_analytics, NULL)) AS Hemoglobin_Analytics,
  MAX(IF(test_name_canonical = 'WHITE BLOOD CELL COUNT', result_value, NULL)) AS WBC_Result,
  MAX(IF(test_name_canonical = 'WHITE BLOOD CELL COUNT', range_text, NULL)) AS WBC_Range,
  MAX(IF(test_name_canonical = 'WHITE BLOOD CELL COUNT', unit_canonical, NULL)) AS WBC_Unit,
  MAX(IF(test_name_canonical = 'WHITE BLOOD CELL COUNT', test_analytics, NULL)) AS WBC_Analytics
FROM `veritas_claims_demo.canonical_records`
WHERE record_type = 'lab_result'
GROUP BY 1,2,3,4,5;
