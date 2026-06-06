CLAIMPILOT — DEMO CASES
========================
Three realistic EPO prosecution cases for demonstration purposes.
Each folder contains two files: specification.txt and office_action.txt.

Upload BOTH files to ClaimPilot (Office Action + Patent Specification),
then click Execute Pipeline to generate the claim chart, translation
verifier, and response draft.

================================================================================
CASE 1 — EP3654128 | 5G NR PDSCH Scheduling (Telecom)
Folder: case1_EP3654128_5G-NR-Scheduling/
================================================================================
Applicant:    Huawei Technologies Co., Ltd.
Domain:       5G New Radio (3GPP Release 15)
Core claim:   Method for dynamic PDSCH scheduling using timing offset K0 from
              a configurable TDRA mapping table signaled via RRC.
OA summary:   Art. 56 objection — D1 (Samsung, WO2018/128361) discloses K0-based
              scheduling; examiner argues RRC configuration of the TDRA table is
              disclosed in D1 and confirmed by 3GPP TS 38.214. Art. 84 clarity
              objection on "receiver" feature in device claim.
Examiner:     Jukka Tapaninen, Division 2.4.03

Key defence angles:
  - Argue D1 uses higher-layer signaling for a fixed table, not a dynamically
    RRC-reconfigurable table as claimed.
  - Emphasise paragraph [0057] on cross-numerology K0 adaptation (not in D1).

================================================================================
CASE 2 — EP3579291 | Adaptive Battery BMS (Clean Energy)
Folder: case2_EP3579291_Battery-BMS/
================================================================================
Applicant:    Contemporary Amperex Technology Co., Ltd. (CATL)
Domain:       Lithium-ion battery management systems
Core claim:   Two-threshold thermal gradient management: proportional current
              reduction (ΔT1) + full suspension with active thermal balancing (ΔT2).
              Formula: I_charge = I_max × (1 - α × (ΔT - ΔT1))
OA summary:   Art. 56 — D1 (Panasonic) discloses single-threshold current reduction;
              D2 (BYD) discloses two-threshold scheme. Examiner combines D1+D2 and
              argues proportional formula is obvious (standard P-control).
              Art. 84 — clarity on I_max SOC dependency and α range support.
Examiner:     Maria Schmidt, Division 3.4.02

Key defence angles:
  - D2 discloses binary (on/off) response at each threshold; claim uses proportional
    reduction between ΔT1 and ΔT2 — neither D1 nor D2 discloses this continuous
    intermediate zone combined with active balancing at ΔT2.
  - Unexpected effect: 11% faster average charging rate (provide test data).

================================================================================
CASE 3 — EP3889891 | AI Defect Detection with Grad-CAM (Industrial AI)
Folder: case3_EP3889891_AI-Defect-Detection/
================================================================================
Applicant:    Siemens Aktiengesellschaft
Domain:       Computer vision / manufacturing quality inspection
Core claim:   Transfer learning (ImageNet → manufacturing defects) with two-phase
              fine-tuning (freeze early layers → joint optimisation at 10× lower LR)
              + Grad-CAM localisation on final convolutional layer.
OA summary:   Art. 56 — D1 (IBM) discloses transfer learning for industrial inspection;
              D3 (Selvaraju 2017 ICCV paper) discloses Grad-CAM; D4 (Yosinski 2014)
              discloses progressive layer unfreezing. Art. 84 — dataset size claim
              unclear; "at least one order of magnitude" ambiguous; product-by-process
              claim in claim 7.
Examiner:     Hans Mueller, Division 3.5.06

Key defence angles:
  - D1 uses unspecified "spatial attention maps" — Grad-CAM on the final layer
    specifically is not disclosed.
  - Two-phase fine-tuning produces 11pp accuracy gain vs single-phase (para [0035]);
    file experimental comparative declaration under Rule 132 EPC.
  - <500 labelled images + >94% accuracy: argue unexpected technical effect.
