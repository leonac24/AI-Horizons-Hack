# Zoning review

Tick a box **only after checking the fact against the linked code section**.
Then run `uv run python -m pipeline.zoning.build_rules --apply`.
Unticked facts stay out of the app (lots show *Needs planner review*).

Legend for use cells: P = by right · A = administrator exception · S = special exception (ZBA) ·
C = conditional use (Council) · - = not permitted (§ 911.01).

## Uses (§ 911.02 and related)

- [ ] `use.single_detached` — § 911.02 ([code](https://ecode360.com/45476524))  
  **R1D P, R1A P, R2 P, R3 P, RM P, P P, H A**  
  > Single-Unit Detached Residential means the use of a zoning lot for one detached housing unit.  
  _Note: The P (Parks) column reads "P" (by right) for a detached house. Surprising for a parks district; confirm against the live table._

- [ ] `use.single_attached` — § 911.02 ([code](https://ecode360.com/45476524))  
  **R1D P/S, R1A P, R2 P, R3 P, RM P, P -, H S**  
  > Single-Unit Attached Residential means the use of a zoning lot for one dwelling unit that is attached to one or more dwelling units  
  _Note: R1D reads "P/S"; see use.single_attached.r1d_width for how that splits._

- [ ] `use.single_attached.r1d_width` — § 911.04.A.69A ([code](https://ecode360.com/45476524))  
  **R1D: by right if lot width ≤ 35 ft, else special exception**  
  > For lots with Lot Widths of 35 feet or smaller, Single-Unit Attached Uses shall be permitted by right.  
  > For lots with Lot Widths larger than 35 feet, Single-Unit Attached Uses shall be permitted by the Special Exception Provisions  
  _Note: Applied using lot frontage from the deed legal description (observed for ~71% of lots). Where frontage is a placeholder, the lot shows Needs planner review for this use._

- [ ] `use.two_unit` — § 911.02 ([code](https://ecode360.com/45476524))  
  **R1D -, R1A -, R2 P, R3 P, RM P, P -, H -**  
  > Two-Unit Residential means the use of a zoning lot for two dwelling units that are contained within a single building.  

- [ ] `use.multi_unit` — § 911.02 ([code](https://ecode360.com/45476524))  
  **R1D -, R1A -, R2 -, R3 -, RM P, P -, H -**  
  > Multi-Unit Residential means the use of a zoning lot for four or more dwelling units that are contained within a single building.  
  _Note: Our "small apartment" (9 homes) and "mid-rise" (32 homes) both map to Multi-Unit (4+)._

- [ ] `use.adu` — § 912.08 ([code](https://ecode360.com/45477814))  
  **R1D -, R1A -, R2 -, R3 -, RM -, P -, H -**  
  > It is the intent of this Section to permit the construction and operation of Accessory Dwelling Units  
  > where Accessory Dwelling Units are permitted subjec  
  _Note: ADUs are allowed only inside a mapped ADU Overlay District, which Lotline does not have. Recorded as not permitted in the base districts. Tick only if you accept "not permitted unless in the overlay" as the default; otherwise leave unticked and ADU stays Needs planner review._

## Dimensional standards

- [ ] `dim.VL.min_lot` — § 903.03.A ([code](https://ecode360.com/45474237))  
  **min_lot_area_sf 6000**  
  > Site Development StandardVery-Low Density SubdistrictMinimum Lot Size6,000 s.f.  

- [ ] `dim.VL.setbacks.low_rise` — § 903.03.A ([code](https://ecode360.com/45474237))  
  **front_setback_ft 30, rear_setback_ft 30, exterior_side_setback_ft 30, interior_side_setback_ft 5, interior_side_other_ft 10**  
  > Minimum Front Setback R1D, R1A, R2 & R3 Subdistricts30 ft.  
  > Minimum Rear Setback R1D, R1A, R2 & R3 Subdistricts30 ft.  
  > R1D, R2 & R3 Subdistricts5 ft, on one side; 10 ft. on the other side  
  _Note: Interior side yard for R1A is 5 ft in every subdistrict; "attached" homes have zero on the party-wall side (903.03.x.2(c)). Contextual setbacks (925.06) may allow less._

- [ ] `dim.VL.setbacks.r1a` — § 903.03.A ([code](https://ecode360.com/45474237))  
  **front_setback_ft 30, rear_setback_ft 30, exterior_side_setback_ft 30, interior_side_setback_ft 5**  
  > Minimum Front Setback R1D, R1A, R2 & R3 Subdistricts30 ft.  
  > Minimum Rear Setback R1D, R1A, R2 & R3 Subdistricts30 ft.  
  > 10 ft. on the other sideR1A Subdistrict5 ft.  
  _Note: Split from dim.VL.setbacks.low_rise, which had applied R1D/R2/R3's 10 ft other-side yard to R1A as well._

- [ ] `dim.VL.setbacks.rm` — § 903.03.A ([code](https://ecode360.com/45474237))  
  **front_setback_ft 30, rear_setback_ft 30, exterior_side_setback_ft 30, interior_side_setback_ft 30**  
  > RM Subdistrict30 ft.Minimum Rear Setback  
  _Note: RM values in Very-Low Density: front 30, rear 30, exterior side 30, interior side 30 ft. Quote shows the first; check the rest in the table._

- [ ] `dim.VL.height.low_rise` — § 903.03.A ([code](https://ecode360.com/45474237))  
  **max_height_ft 40, max_stories 3**  
  > Maximum Height R1D, R1A, R2 & R3 Subdistricts40 ft. (not to exceed 3 stories)  

- [ ] `dim.VL.height.rm` — § 903.03.A ([code](https://ecode360.com/45474237))  
  **max_height_ft 40, max_stories 3**  
  > RM Subdistrict40 ft. (not to exceed 3 stories)  

- [ ] `dim.L.min_lot` — § 903.03.B ([code](https://ecode360.com/45474237))  
  **min_lot_area_sf 3000**  
  > Site Development StandardLow Density SubdistrictMinimum Lot Size3,000 s.f.  

- [ ] `dim.L.setbacks.low_rise` — § 903.03.B ([code](https://ecode360.com/45474237))  
  **front_setback_ft 30, rear_setback_ft 30, exterior_side_setback_ft 30, interior_side_setback_ft 5**  
  > Minimum Front Setback R1D, R1A, R2 & R3 Subdistricts30 ft.  
  > Minimum Rear Setback R1D, R1A, R2 & R3 Subdistricts30 ft.  
  _Note: Interior side yard for R1A is 5 ft in every subdistrict; "attached" homes have zero on the party-wall side (903.03.x.2(c)). Contextual setbacks (925.06) may allow less._

- [ ] `dim.L.setbacks.rm` — § 903.03.B ([code](https://ecode360.com/45474237))  
  **front_setback_ft 25, rear_setback_ft 25, exterior_side_setback_ft 30, interior_side_setback_ft 25**  
  > RM Subdistrict25 ft.Minimum Rear Setback  
  _Note: RM values in Low Density: front 25, rear 25, exterior side 30, interior side 25 ft. Quote shows the first; check the rest in the table._

- [ ] `dim.L.height.low_rise` — § 903.03.B ([code](https://ecode360.com/45474237))  
  **max_height_ft 40, max_stories 3**  
  > Maximum Height R1D, R1A, R2 & R3 Subdistricts40 ft. (not to exceed 3 stories)  

- [ ] `dim.L.height.rm` — § 903.03.B ([code](https://ecode360.com/45474237))  
  **max_height_ft 40, max_stories 3**  
  > RM Subdistrict40 ft. (not to exceed 3 stories)  

- [ ] `dim.M.min_lot` — § 903.03.C ([code](https://ecode360.com/45474237))  
  **min_lot_area_sf 2400**  
  > Site Development StandardModerate Density SubdistrictMinimum Lot Size2,400 s.f.  

- [ ] `dim.M.setbacks.low_rise` — § 903.03.C ([code](https://ecode360.com/45474237))  
  **front_setback_ft 30, rear_setback_ft 30, exterior_side_setback_ft 30, interior_side_setback_ft 5**  
  > Minimum Front Setback R1D, R1A, R2 & R3 Subdistricts30 ft.  
  > Minimum Rear Setback R1D, R1A, R2 & R3 Subdistricts30 ft.  
  _Note: Interior side yard for R1A is 5 ft in every subdistrict; "attached" homes have zero on the party-wall side (903.03.x.2(c)). Contextual setbacks (925.06) may allow less._

- [ ] `dim.M.setbacks.rm` — § 903.03.C ([code](https://ecode360.com/45474237))  
  **front_setback_ft 25, rear_setback_ft 25, exterior_side_setback_ft 25, interior_side_setback_ft 10**  
  > RM Subdistrict25 ft.Minimum Rear Setback  
  _Note: RM values in Moderate Density: front 25, rear 25, exterior side 25, interior side 10 ft. Quote shows the first; check the rest in the table._

- [ ] `dim.M.height.low_rise` — § 903.03.C ([code](https://ecode360.com/45474237))  
  **max_height_ft 40, max_stories 3**  
  > Maximum Height R1D, R1A, R2 & R3 Subdistricts40 ft. (not to exceed 3 stories)  

- [ ] `dim.M.height.rm` — § 903.03.C ([code](https://ecode360.com/45474237))  
  **max_height_ft 55, max_stories 4**  
  > RM Subdistrict55 ft. (not to exceed 4 stories)  

- [ ] `dim.H.min_lot` — § 903.03.D ([code](https://ecode360.com/45474237))  
  **min_lot_area_sf 1200**  
  > Site Development StandardHigh Density SubdistrictMinimum Lot Size1,200 s.f.  

- [ ] `dim.H.setbacks.low_rise` — § 903.03.D ([code](https://ecode360.com/45474237))  
  **front_setback_ft 15, rear_setback_ft 15, exterior_side_setback_ft 15, interior_side_setback_ft 5**  
  > Minimum Front Setback R1D, R1A, R2 & R3 Subdistricts15 ft.  
  > Minimum Rear Setback R1D, R1A, R2 & R3 Subdistricts15 ft.  
  _Note: Interior side yard for R1A is 5 ft in every subdistrict; "attached" homes have zero on the party-wall side (903.03.x.2(c)). Contextual setbacks (925.06) may allow less._

- [ ] `dim.H.setbacks.rm` — § 903.03.D ([code](https://ecode360.com/45474237))  
  **front_setback_ft 25, rear_setback_ft 25, exterior_side_setback_ft 25, interior_side_setback_ft 10**  
  > RM Subdistrict25 ft.Minimum Rear Setback  
  _Note: RM values in High Density: front 25, rear 25, exterior side 25, interior side 10 ft. Quote shows the first; check the rest in the table._

- [ ] `dim.H.height.low_rise` — § 903.03.D ([code](https://ecode360.com/45474237))  
  **max_height_ft 40, max_stories 3**  
  > Maximum Height R1D, R1A, R2 & R3 Subdistricts40 ft. (not to exceed 3 stories)  

- [ ] `dim.H.height.rm` — § 903.03.D ([code](https://ecode360.com/45474237))  
  **max_height_ft 85, max_stories 9**  
  > RM Subdistrict85 ft. (not to exceed 9 stories)  

- [ ] `dim.VH.setbacks.low_rise` — § 903.03.E ([code](https://ecode360.com/45474237))  
  **front_setback_ft 5, rear_setback_ft 15, exterior_side_setback_ft 5, interior_side_setback_ft 5**  
  > Minimum Front Setback R1D, R1A, R2 & R3 Subdistricts5 ft.  
  > Minimum Rear Setback R1D, R1A, R2 & R3 Subdistricts15 ft.  
  _Note: Interior side yard for R1A is 5 ft in every subdistrict; "attached" homes have zero on the party-wall side (903.03.x.2(c)). Contextual setbacks (925.06) may allow less._

- [ ] `dim.VH.setbacks.rm` — § 903.03.E ([code](https://ecode360.com/45474237))  
  **front_setback_ft 25, rear_setback_ft 25, exterior_side_setback_ft 25, interior_side_setback_ft 10**  
  > RM Subdistrict25 ft.Minimum Rear Setback  
  _Note: RM values in Very-High Density: front 25, rear 25, exterior side 25, interior side 10 ft. Quote shows the first; check the rest in the table._

- [ ] `dim.VH.height.low_rise` — § 903.03.E ([code](https://ecode360.com/45474237))  
  **max_height_ft 40, max_stories 3**  
  > Maximum Height R1D, R1A, R2 & R3 Subdistricts40 ft. (not to exceed 3 stories)  

- [ ] `dim.VH.height.rm` — § 903.03.E ([code](https://ecode360.com/45474237))  
  **max_height_ft 180**  
  > RM Subdistrict180 ft.  

- [ ] `dim.P` — § 905.01.C ([code](https://ecode360.com/45474542))  
  **min_lot_area_sf 3200, front_setback_ft 30, rear_setback_ft 20, exterior_side_setback_ft 20, interior_side_setback_ft 5, max_height_ft 40, max_stories 3**  
  > Site Development StandardP DistrictMinimum Lot Size3,200 s.f.  
  > Minimum Front Setback30 ft.Minimum Rear Setback20 ft.  
  > Maximum Height40 ft. (not to exceed 3 stories)  

- [ ] `dim.H` — § 905.02.C ([code](https://ecode360.com/45474542))  
  **min_lot_area_sf 3200, front_setback_ft 0, rear_setback_ft 0, exterior_side_setback_ft 0, interior_side_setback_ft 0, max_height_ft 40, max_stories 3**  
  > Site Development StandardH DistrictMinimum Lot Size3,200 s.f.  
  > Minimum Front SetbacknoneMinimum Rear Setbacknone  
  > Maximum Height40 ft. (not to exceed 3 stories)  
  _Note: Also: maximum area of disturbance 50% of lot, Site Plan Review for building permits, and single-unit homes must sit on land under 30% slope (911.04.A.69). Those are shown as notes, not checked._
