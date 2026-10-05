# Author-provided sources: acquisition and validation plan

Reviewed 2026-10-05. The owner supplied Dr Opeyemi Aniramu's provider list after
the underlying-data request was declined. This is a source-discovery lead, not
permission to use the restricted study files, and not scientific acceptance.
No source listed here has been newly imported into production or depth training.

## Decisions by source

| Source and primary reference | Use in FloodSight | Access/rights and next decision |
|---|---|---|
| [CHIRPS v3](https://www.chc.ucsb.edu/data/chirps3), [v2 notice](https://www.chc.ucsb.edu/data/chirps) | Historical rainfall covariate and comparison with station records | v3 is available; v2 production ends after December 2026. Publisher mentions both public domain and CC BY 4.0; preserve attribution conservatively and archive the exact file's terms. Pin version, final/preliminary status, daily rnl/sat variant, dates, units and checksum. Assess a separate transition, not an untested replacement. |
| [NiMet data policy](https://nimet.gov.ng/admin/uploads/NIMET%20DATA%20POLICY-2SUUFhcs-6.pdf) | Station rainfall to check precipitation forcing | Requests must identify intended use, with approval and applicable fees. Request Lagos station inventory, hourly/daily availability, accumulation windows, coordinates, relocations and QC. Disclose intended commercial use; obtain explicit permitted-use/redistribution terms. No request or payment made here. |
| [NIHSA](https://nihsa.gov.ng), Ogun-Oshun River Basin Development Authority (paper's original provider) | Discharge/water-level event checks where basin and station coverage match | Agency-level request lead, not an acquired open dataset. Confirm actual stations, dates, datum, rating curves, QC and rights. River discharge in m3/s or gauge elevation is not street inundation depth above ground. |
| [GRDC data portal](https://grdc.bafg.de/data/data_portal/) | Potential hydrological research reference | Standard terms prohibit commercial use of original data. Exclude from commercial-product ingestion pending written authorization; do not substitute free research access for permission. Nigerian/Lagos station availability has not been verified. |
| [Sentinel-1/CDSE](https://dataspace.copernicus.eu), [Copernicus data policy](https://www.copernicus.eu/en/frequently-asked-questions) | Event-matched SAR flood-extent research | Sentinel data have full, free, open access; archive applicable terms and attribution for each product. Acquire before/after imagery and masks. Urban radar shadow, layover, permanent water and acquisition timing limit evidence. Extent is not measured depth; correlation with existing SAR proxy labels limits independence. |
| [Official CEMS Global Flood Monitoring](https://global-flood.emergency.copernicus.eu/), [terms](https://global-flood.emergency.copernicus.eu/terms-of-service/) | Candidate reproducible extent benchmark on new events/sites | Official terms allow open reuse with attribution and conditions; third-party inputs may differ. Author's globalfloodmonitoring.org address could not be verified as this service. Use the official route, not similarly named social-media event trackers. Require valid-observation/exclusion/permanent-water masks; excluded pixels must not become dry controls. Lagos/event coverage still needs checking. |
| [UNOSAT](https://unosat.org), [Nigeria example](https://unosat.org/products/3961) | Independent-provider extent comparisons where coverage overlaps | Inspect each product's geography, dates, sensor, confidence and resource-specific rights. Previously reviewed Nigeria/Mokwa products do not establish Lagos coverage. Preliminary satellite analyses are not field-validated depth. |
| [EM-DAT terms](https://doc.emdat.be/docs/legal/terms-of-use/) | Major-event discovery/context only | Commercial use and derived products require a separate agreement. Do not import under academic/free access for FloodSight without authorization. Disaster inclusion criteria mean an absent record is not a verified non-flood event. No agreement or download made. |
| [USGS SRTM 1 arc-second](https://www.usgs.gov/centers/eros/science/usgs-eros-archive-digital-elevation-shuttle-radar-topography-mission-srtm-1) | Terrain input; assess drainage and elevation limitations | Approximately 30 m source terrain is not 200 m street-depth observation. Pin tiles, vertical reference, void filling and processing. Existing terrain-derived labels and features can share errors; do not count their agreement as independent validation. |
| [Copernicus Global Dynamic Land Cover](https://land.copernicus.eu/en/products/global-dynamic-land-cover?tab=overview), [licence](https://cds.climate.copernicus.eu/licences/Copernicus-Global-Land-product-licence) | Versioned land-cover/imperviousness covariates and sensitivity analysis | Free/open reuse with source/adaptation attribution. Legacy 100 m annual maps cover 2015-2019; newer 10 m service is distinct. Match product, observation year, classes, confidence and dates to the evaluated event; a newer grid must not leak future urbanization into an older replay. |
| [FAO HWSD v2 portal](https://www.fao.org/soils-portal/data-hub/soil-maps-and-databases/harmonized-world-soil-database-v20/en/), [specific FAO derivative](https://data.fao.org/catalog/dataset/00ff0022-2369-461d-b353-7e03a61cb5c9) | Optional coarse soil/infiltration covariate | Exact archive licence unresolved. Older HWSD documentation restricts commercial redistribution/use; a particular FAO derivative lists CC BY-SA 4.0. Do not transfer that licence to the entire database. Verify exact version/file and obligations before acquisition; approximately 1 km soil properties cannot represent street drainage. |
| [USACE HEC-HMS](https://www.hec.usace.army.mil/software/hec-hms/) | Hydrological-method replication and rainfall-runoff baseline | Software/docs, not an observation dataset. Requires catchments, parameters and forcing. Its simulated runoff cannot validate FloodSight against itself, establish street depth, or inherit another study's performance. No installation needed for the current evidence intake. |

CHIRPS's 0.05-degree grid is roughly 5.5 km at Lagos, not street-scale rainfall.
v3 daily totals are disaggregated from coarser time periods using ERA5 or IMERG
weights. Record the accumulation conventions before station comparison. Historical
final products may become available after an event: they cannot establish what a
forecast knew 24/72 hours beforehand or prove operational lead time.

## Five papers: retain as method/context, not depth truth

- [Idowu & Zhou, Water 2021, 10.3390/w13081105](https://res.mdpi.com/d_attachment/water/water-13-01105/article_deploy/water-13-01105.pdf): LULC change and weighted hazard mapping; useful alternative susceptibility-method reference. Publisher PDF/abstract/method section reviewed; article marked CC BY 4.0. Not an acquired event/site measured-depth dataset.
- [Lawanson et al., 10.1111/jfr3.12838](https://onlinelibrary.wiley.com/doi/abs/10.1111/jfr3.12838): impacts on poor communities in Makoko; useful pilot vulnerability and messaging context. Publisher citation/abstract discovery only; full results and dataset rights not reviewed.
- [Kasim et al., 10.1080/17477891.2021.1932404](https://www.tandfonline.com/doi/abs/10.1080/17477891.2021.1932404): urban expansion and flood risk; useful land-use/planning sensitivity reference. Publisher abstract reviewed, not full results or a permitted measurement archive.
- [Nkwunonwo et al., 10.5194/nhess-16-349-2016](https://nhess.copernicus.org/articles/16/349/2016/): review of Lagos flood-risk management; useful historical event/source and institutional discovery. Open article marked CC BY 3.0; references must be traced individually, not treated as new observations.
- [Bako & Ojolowo, 10.4102/jamba.v13i1.825](https://pmc.ncbi.nlm.nih.gov/articles/PMC8008089/): spatial knowledge and preparedness in Victoria Island; useful UX/field questionnaire context. Available abstract/archived article discovery, not a newly obtained ground-referenced depth table.

Article access/licensing never automatically grants permission to underlying
third-party datasets. Do not copy adapted figures or restricted data into product
assets. This is a technical rights screening, not legal clearance.

## Prioritized next intake

1. Build an event/acquisition inventory for official CEMS GFM and Sentinel-1
   overlapping the actual service cells, separating already tuned events from
   genuinely new sites/events. Check valid-observation masks before downloading
   a bounded Lagos subset. Freeze the evaluation plan before fitting thresholds.
2. Assess CHIRPS v3 against the current v2 pipeline on overlapping historical
   periods; keep a named, versioned comparison. NiMet station data are the
   independent rainfall comparison target, subject to owner-approved requests
   and fees. This is forcing validation, not flood-depth acceptance.
3. Obtain local ground-referenced measured depth AND fixed-site dry observations
   through the local field-research lead and agency/field partnerships described
   in SCIENTIFIC_VALIDATION.md. Independent wet/dry measurement remains the
   highest scientific blocker. No additional outreach sent here.
4. Match observations to archived issued forecasts, not retrospectively fetched
   weather. Hold out entire events and sites; compare against simple baselines,
   report misses/false alarms/lead time separately from depth RMSE.

Every acquisition must retain source/product/version, exact files/checksums,
licence snapshot/attribution, coordinates/CRS/vertical datum, timing/timezone,
measurement type, uncertainty/QC, reviewer and overlap with training/tuning.
No-report, no-data, clouds or sensor exclusions are not dry labels. A repeat
news report is not an independent event. The prior historical evidence freeze is
unchanged by this plan.

Decision: use cleared sources to build reproducible input/extent evidence;
seek measured local observations for depth and prospective warning acceptance.
Experimental depth and public SMS remain disabled pending their separate gates.
