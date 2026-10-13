-- ResFinance Milestone 0: bounded GDELT GKG daily sentiment extraction.
--
-- Run only in Google BigQuery Sandbox or another project with billing disabled.
-- Before running the full query, use the console query validator to confirm the
-- estimated bytes processed fit within the remaining free query allowance.
-- The query reads the public partitioned GKG table and returns aggregates only;
-- it does not create a table or persist copyrighted article text.

DECLARE period_start DATE DEFAULT DATE '2020-04-10';
DECLARE period_end DATE DEFAULT DATE '2025-01-01';

WITH
  calendar AS (
    SELECT day
    FROM UNNEST(GENERATE_DATE_ARRAY(period_start, period_end)) AS day
  ),
  assets AS (
    SELECT asset, name_pattern
    FROM UNNEST([
      STRUCT('BTC' AS asset, r'(^|[^a-z])bitcoin([^a-z]|$)' AS name_pattern),
      STRUCT('ETH' AS asset, r'(^|[^a-z])ethereum([^a-z]|$)' AS name_pattern),
      STRUCT('SOL' AS asset, r'(^|[^a-z])solana([^a-z]|$)' AS name_pattern)
    ])
  ),
  bounded_gkg AS (
    SELECT
      PARSE_DATE('%Y%m%d', SUBSTR(CAST(DATE AS STRING), 1, 8)) AS day,
      DocumentIdentifier AS document_id,
      SourceCommonName AS source_name,
      SAFE_CAST(SPLIT(V2Tone, ',')[SAFE_OFFSET(0)] AS FLOAT64) AS tone,
      LOWER(
        CONCAT(
          IFNULL(AllNames, ''),
          ' ',
          IFNULL(V2Organizations, '')
        )
      ) AS named_entities
    FROM `gdelt-bq.gdeltv2.gkg_partitioned`
    WHERE
      _PARTITIONTIME >= TIMESTAMP('2020-04-10')
      AND _PARTITIONTIME < TIMESTAMP('2025-01-02')
      AND DATE >= 20200410000000
      AND DATE < 20250102000000
  ),
  matched AS (
    SELECT
      gkg.day,
      asset_dim.asset,
      gkg.document_id,
      gkg.source_name,
      gkg.tone
    FROM bounded_gkg AS gkg
    CROSS JOIN assets AS asset_dim
    WHERE REGEXP_CONTAINS(gkg.named_entities, asset_dim.name_pattern)
    QUALIFY
      ROW_NUMBER() OVER (
        PARTITION BY gkg.day, asset_dim.asset, gkg.document_id
        ORDER BY gkg.source_name, gkg.tone
      ) = 1
  ),
  daily AS (
    SELECT
      day,
      asset,
      COUNT(*) AS document_count,
      COUNT(DISTINCT source_name) AS source_count,
      COUNT(tone) AS tone_observation_count,
      AVG(tone) AS average_tone,
      COUNTIF(tone > 0) AS positive_document_count,
      COUNTIF(tone < 0) AS negative_document_count,
      COUNTIF(tone = 0) AS neutral_document_count
    FROM matched
    GROUP BY day, asset
  )
SELECT
  calendar.day,
  assets.asset,
  COALESCE(daily.document_count, 0) AS document_count,
  COALESCE(daily.source_count, 0) AS source_count,
  COALESCE(daily.tone_observation_count, 0) AS tone_observation_count,
  daily.average_tone,
  COALESCE(daily.positive_document_count, 0) AS positive_document_count,
  COALESCE(daily.negative_document_count, 0) AS negative_document_count,
  COALESCE(daily.neutral_document_count, 0) AS neutral_document_count
FROM calendar
CROSS JOIN assets
LEFT JOIN daily USING (day, asset)
ORDER BY calendar.day, assets.asset;
