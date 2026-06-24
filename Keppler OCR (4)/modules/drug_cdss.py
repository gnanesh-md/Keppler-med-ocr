# modules/drug_cdss.py  — Clinical Decision Support System v1.0
"""
Drug CDSS — Takes patient profile + selected drug(s) → evaluates all
clinical rules from the drug monography JSON → returns structured alerts
with severity levels: CONTRAINDICATED / HIGH / MODERATE / LOW / INFO

Integration: add to app.py as a new client template "Drug CDSS"
"""

import streamlit as st
import json
import re
import os
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────
CDSS_JSON_PATH = Path(__file__).parent.parent / "datasets" / "drug_cdss_schema.json"

SEVERITY_ORDER  = ["CONTRAINDICATED", "HIGH", "MODERATE", "LOW", "INFO"]
SEVERITY_COLORS = {
    "CONTRAINDICATED": "#ff4b4b",
    "HIGH":            "#ff8c00",
    "MODERATE":        "#ffd700",
    "LOW":             "#2196F3",
    "INFO":            "#4caf50",
}
SEVERITY_ICONS = {
    "CONTRAINDICATED": "🚫",
    "HIGH":            "⚠️",
    "MODERATE":        "🔶",
    "LOW":             "ℹ️",
    "INFO":            "✅",
}

# ─────────────────────────────────────────────────────────────────────────────
# LOAD CDSS DATA
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_resource
def load_cdss_data() -> dict:
    try:
        raw = open(CDSS_JSON_PATH, 'rb').read()
        # Fix control characters inside JSON string values
        fixed = bytearray()
        in_string  = False
        esc_next   = False
        for b in raw:
            if esc_next:
                fixed.append(b)
                esc_next = False
            elif b == ord('\\'):
                fixed.append(b)
                esc_next = True
            elif b == ord('"'):
                fixed.append(b)
                in_string = not in_string
            elif in_string and b in (10, 13):
                fixed.append(ord(' '))
            elif in_string and b < 32:
                fixed.append(ord(' '))
            else:
                fixed.append(b)
        return json.loads(fixed.decode('utf-8'))
    except Exception as e:
        st.error(f"Failed to load CDSS data: {e}")
        return {}


def get_available_drugs(cdss_data: dict) -> list[str]:
    return [d["name"] for d in cdss_data.get("drugs", [])]


def get_drug_data(cdss_data: dict, drug_name: str) -> dict | None:
    for d in cdss_data.get("drugs", []):
        if d["name"].lower() == drug_name.lower():
            return d
    return None

# ─────────────────────────────────────────────────────────────────────────────
# CDSS ENGINE — evaluate rules against patient profile
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_drug(patient: dict, labs: dict, drug_data: dict) -> list[dict]:
    """
    Returns a list of alert dicts:
    { severity, category, message, rule_name }
    """
    alerts = []
    rules  = drug_data.get("cdss_rules", {})
    name   = drug_data.get("name", "Drug")

    def add(severity, category, message, rule=""):
        alerts.append({
            "severity": severity,
            "category": category,
            "message":  message,
            "drug":     name,
            "rule":     rule,
        })

    # ── 1. BOX WARNING (always show) ─────────────────────────────────────────
    box = rules.get("box_warning", {})
    for k, v in box.items():
        if k != "note" and isinstance(v, str):
            add("HIGH", "⬛ Box Warning", v, k)

    # ── 2. CONTRAINDICATIONS ────────────────────────────────────────────────
    contra = rules.get("contraindications", {})

    # Allergy check
    allergy_hist = [a.lower() for a in patient.get("allergy_history", [])]
    trigger_drugs = {
        "Diclofenac": ["diclofenac","nsaid","aspirin","ibuprofen","naproxen","nsaids"],
        "Amoxicillin": ["amoxicillin","penicillin","ampicillin","beta-lactam"],
    }
    for drug_key, allergens in trigger_drugs.items():
        if drug_key.lower() == name.lower():
            if any(a in " ".join(allergy_hist) for a in allergens):
                add("CONTRAINDICATED", "Allergy", contra.get("hypersensitivity_to_drug", "Allergy to this drug detected."), "allergy")

    # Pregnancy trimester check (Diclofenac specific)
    if patient.get("pregnancy") == "Yes":
        tri = patient.get("pregnancy_trimester", "").lower()
        preg_rules = rules.get("warnings_by_condition", {}).get("pregnancy", {})
        tri_rules  = preg_rules.get("trimester_rules", {})
        for tri_key, tri_data in tri_rules.items():
            if tri_key in tri or tri == "third":
                add(tri_data["severity"], f"Pregnancy ({tri_data.get('category','')})",
                    tri_data["message"], "pregnancy")
                break
        if not tri_rules:
            # Simple pregnancy warning (Amoxicillin)
            if preg_rules:
                add(preg_rules.get("severity","LOW"),
                    f"Pregnancy ({preg_rules.get('category','')}) ",
                    preg_rules.get("message","Use with caution in pregnancy."),
                    "pregnancy")

    # Breastfeeding
    if patient.get("breastfeeding") == "Yes":
        bf_rule = rules.get("warnings_by_condition", {}).get("breastfeeding", {})
        if bf_rule:
            add(bf_rule.get("severity","MODERATE"), "Breastfeeding",
                bf_rule.get("message","Use with caution during breastfeeding."), "breastfeeding")

    # ── 3. CONDITION-BASED WARNINGS ─────────────────────────────────────────
    w = rules.get("warnings_by_condition", {})

    # CV risk
    cv_rule = w.get("cv_risk", {})
    if cv_rule:
        comorbid_lower  = [c.lower() for c in patient.get("comorbid", [])]
        cv_hist_lower   = [c.lower() for c in patient.get("cv_history", [])]
        triggers        = [t.lower() for t in cv_rule.get("trigger_values", [])]
        all_conditions  = comorbid_lower + cv_hist_lower
        if any(any(t in c for t in triggers) for c in all_conditions):
            add(cv_rule["severity"], "CV Risk", cv_rule["message"], "cv_risk")

    # GI risk
    gi_rule = w.get("gi_risk", {})
    if gi_rule:
        gi_flags   = [c.lower() for c in patient.get("gi_risk", [])]
        hi_meds    = [c.lower() for c in patient.get("high_risk_meds", [])]
        comorbid   = [c.lower() for c in patient.get("comorbid", [])]
        triggers   = [t.lower() for t in gi_rule.get("trigger_values", [])]
        all_f      = gi_flags + hi_meds + comorbid
        if any(any(t in f for t in triggers) for f in all_f):
            add(gi_rule["severity"], "GI Risk", gi_rule["message"], "gi_risk")

    # Renal risk
    renal_rule = w.get("renal_risk", {}) or w.get("renal_impairment", {})
    if renal_rule:
        egfr  = labs.get("egfr")
        crcl  = labs.get("crcl")
        cr    = labs.get("creatinine")
        renal_flag = False
        dose_adj_msg = ""

        if egfr is not None and egfr < 30:
            renal_flag = True
            dose_adj = renal_rule.get("dose_adjustment", {})
            if dose_adj:
                dose_adj_msg = f" Dose adjustment: eGFR 10-30 → {dose_adj.get('egfr_10_30','')}; eGFR <10 → {dose_adj.get('egfr_less_10','')}."
        elif egfr is not None and egfr < 60:
            renal_flag = True

        comorbid_lower = [c.lower() for c in patient.get("comorbid", [])]
        triggers = [t.lower() for t in renal_rule.get("trigger_values", [])]
        if any(any(t in c for t in triggers) for c in comorbid_lower):
            renal_flag = True

        if patient.get("dialysis_status") not in (None, "None", ""):
            renal_flag = True

        if renal_flag:
            add(renal_rule.get("severity","HIGH"), "Renal Impairment",
                renal_rule.get("message","") + dose_adj_msg, "renal")

    # Hepatic risk
    hep_rule = w.get("hepatic_risk", {})
    if hep_rule:
        hep = patient.get("hepatic_impairment","None")
        liver = patient.get("liver_disease_type","None")
        triggers = [t.lower() for t in hep_rule.get("trigger_values",[])]
        if hep not in ("None","") or liver not in ("None",""):
            if any(t in (hep+liver).lower() for t in triggers):
                add(hep_rule["severity"], "Hepatic Impairment",
                    hep_rule["message"], "hepatic")

    # Geriatric
    ger_rule = w.get("geriatric", {})
    if ger_rule:
        age_thresh = ger_rule.get("age_threshold", 65)
        if patient.get("age", 0) >= age_thresh:
            add(ger_rule["severity"], "Geriatric Patient", ger_rule["message"], "geriatric")

    # Alcohol
    alc_rule = w.get("alcohol", {})
    if alc_rule:
        alc = patient.get("alcohol_use","None")
        triggers = [t.lower() for t in alc_rule.get("trigger_values",[])]
        if alc.lower() in triggers:
            add(alc_rule["severity"], "Alcohol Use", alc_rule["message"], "alcohol")

    # Smoking
    smk_rule = w.get("smoking", {})
    if smk_rule:
        smk = patient.get("smoking_status","")
        triggers = [t.lower() for t in smk_rule.get("trigger_values",[])]
        if any(t in smk.lower() for t in triggers):
            add(smk_rule["severity"], "Smoking", smk_rule["message"], "smoking")

    # Dose check (Diclofenac)
    dose_rule = w.get("dose_check", {})
    if dose_rule:
        prescribed = drug_data.get("dose_value", 0)
        max_dose   = dose_rule.get("max_daily_oral_mg", 9999)
        if prescribed > max_dose:
            add(dose_rule["severity"], "Dose Alert",
                f"Prescribed dose {prescribed}mg exceeds maximum recommended {max_dose}mg/day. "
                + dose_rule.get("message",""), "dose_check")

    # CDAD risk (Amoxicillin)
    cdad_rule = w.get("cdad_risk", {})
    if cdad_rule:
        comorbid_lower = [c.lower() for c in patient.get("comorbid",[])]
        hi_meds_lower  = [c.lower() for c in patient.get("high_risk_meds",[])]
        triggers = [t.lower() for t in cdad_rule.get("trigger_values",[])]
        all_f = comorbid_lower + hi_meds_lower
        if any(any(t in f for t in triggers) for f in all_f):
            add(cdad_rule["severity"], "CDAD Risk", cdad_rule["message"], "cdad")

    # ── 3.5 GENERIC WARNINGS (from schema) ──────────────────────────────────
    # Evaluate any other warnings automatically by checking flat patient text
    patient_text = " ".join([str(v) for v in patient.values()]).lower()
    for rule_name, rule_data in w.items():
        if rule_name in ["pregnancy", "breastfeeding", "cv_risk", "gi_risk", "renal_risk", "hepatic_risk", "geriatric", "alcohol", "smoking", "dose_check", "cdad_risk"]:
            continue
            
        triggers = [t.lower() for t in rule_data.get("trigger_values", [])]
        if triggers and any(t in patient_text for t in triggers):
            title = rule_data.get("title", rule_name.replace("_", " ").title())
            add(rule_data.get("severity", "MODERATE"), title, rule_data.get("message", ""), rule_name)

    # ── 4. Sort by severity order ─────────────────────────────────────────────
    alerts.sort(key=lambda a: SEVERITY_ORDER.index(a["severity"])
                if a["severity"] in SEVERITY_ORDER else 99)

    # ── 5. If no alerts — add safe INFO ──────────────────────────────────────
    if not alerts:
        add("INFO", "No Alerts", f"No clinical warnings identified for {name} based on the provided patient profile.", "none")

    return alerts


# ─────────────────────────────────────────────────────────────────────────────
# STREAMLIT UI
# ─────────────────────────────────────────────────────────────────────────────

def render_drug_cdss():
    st.header("💊 Drug CDSS — Clinical Decision Support")
    st.caption("Enter patient details → select drug → get instant clinical safety alerts from drug monography")

    cdss_data = load_cdss_data()
    if not cdss_data:
        st.error("CDSS data not loaded. Check datasets/drug_cdss_schema.json")
        return

    available_drugs = get_available_drugs(cdss_data)

    # ── MAIN CONTENT: Patient Input Form ──────────────────────────────────────
    with st.form("cdss_patient_form"):
        st.markdown("### 👤 Patient Profile")

        # Row 1: Demographics
        col1, col2, col3 = st.columns(3)
        with col1:
            age    = st.number_input("Age (years)", 0, 120, 45, key="cdss_age")
        with col2:
            gender = st.selectbox("Gender", ["Male","Female","Other"], key="cdss_gender")
        with col3:
            weight = st.number_input("Weight (kg)", 1, 300, 65, key="cdss_weight")

        # Row 2: Special Populations
        st.markdown("**Special Populations**")
        col1, col2, col3 = st.columns(3)
        with col1:
            pregnancy = st.selectbox("Pregnancy", ["No","Yes"], key="cdss_preg")
        with col2:
            preg_tri  = st.selectbox("Trimester (if pregnant)", ["NOT_APPLICABLE","first","second","third"], key="cdss_tri")
        with col3:
            breastfeeding = st.selectbox("Breastfeeding", ["No","Yes"], key="cdss_bf")

        # Row 3: Comorbidities & Risk Factors
        st.markdown("**Comorbidities & Risk Factors**")
        col1, col2 = st.columns(2)
        with col1:
            comorbid_opts = ["hypertension","heart_disease","MI","stroke","heart_failure",
                             "diabetes","CKD","renal_disease","peptic_ulcer","GI_bleed",
                             "IBD","cirrhosis","hepatitis","COPD","asthma","immunocompromised",
                             "infectious_mononucleosis", "phenylketonuria", "lymphatic_leukaemia"]
            comorbid = st.multiselect("Comorbid Conditions", comorbid_opts, key="cdss_comorbid")

            cv_opts  = ["MI","stroke","heart_failure","ischemic_heart_disease","CABG"]
            cv_hist  = st.multiselect("CV History", cv_opts, key="cdss_cv")
        with col2:
            gi_opts  = ["peptic_ulcer","GI_bleed","gastritis","IBD"]
            gi_risk  = st.multiselect("GI Risk Factors", gi_opts, key="cdss_gi")

            med_opts = ["anticoagulant","aspirin","steroid","SSRI","ACE_inhibitor",
                        "antibiotic_recent","methotrexate"]
            hi_meds  = st.multiselect("High Risk Co-medications", med_opts, key="cdss_meds")

        # Row 4: Allergy, Hepatic, Lifestyle
        st.markdown("**Allergy & Lifestyle**")
        col1, col2, col3 = st.columns(3)
        with col1:
            allergy  = st.multiselect("Allergy History",
                                      ["Diclofenac","NSAIDs","Aspirin","Penicillin",
                                       "Amoxicillin","Cephalosporin","Carbapenem","Monobactam",
                                       "Sulfa","Codeine"],
                                      key="cdss_allergy")
            hep_imp  = st.selectbox("Hepatic Impairment",
                                    ["None","mild","moderate","severe"], key="cdss_hep")
        with col2:
            dialysis = st.selectbox("Dialysis Status",
                                    ["None","haemodialysis","peritoneal"], key="cdss_dial")
            smoking  = st.selectbox("Smoking Status",
                                    ["Non-smoker","Smoker","Ex-smoker"], key="cdss_smoke")
        with col3:
            alcohol  = st.selectbox("Alcohol Use",
                                    ["None","occasional","moderate","heavy"], key="cdss_alc")

        # Row 5: Lab Values
        st.markdown("### 🧪 Lab Values")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            creatinine = st.number_input("Creatinine (mg/dL)", 0.0, 20.0, 0.0,
                                         step=0.1, key="cdss_cr")
        with col2:
            egfr       = st.number_input("eGFR (mL/min)", 0.0, 200.0, 0.0,
                                         step=1.0, key="cdss_egfr")
        with col3:
            alt        = st.number_input("ALT (U/L)", 0.0, 2000.0, 0.0,
                                         step=1.0, key="cdss_alt")
        with col4:
            hemoglobin = st.number_input("Haemoglobin (g/dL)", 0.0, 25.0, 0.0,
                                         step=0.1, key="cdss_hgb")

        # Row 6: Drug Selection + Submit
        st.markdown("### 💊 Drug Selection")
        col1, col2 = st.columns([3, 1])
        with col1:
            selected_drugs = st.multiselect("Select Drug(s) to Evaluate", available_drugs,
                                            default=[available_drugs[0]] if available_drugs else [],
                                            key="cdss_drugs")
        with col2:
            st.markdown("<br>", unsafe_allow_html=True)

        run_btn = st.form_submit_button("🔍 Evaluate Safety", type="primary", use_container_width=True)

    # Fix trimester if pregnancy is No
    if pregnancy == "No":
        preg_tri = "NOT_APPLICABLE"

    # ── RESULTS SECTION ───────────────────────────────────────────────────────
    if not run_btn and "cdss_last_result" not in st.session_state:
        _show_cdss_guide()
        return

    if run_btn:
        if not selected_drugs:
            st.warning("Please select at least one drug to evaluate.")
            return

        patient = {
            "age": age, "gender": gender, "weight": weight,
            "age_group": "pediatric" if age < 18 else ("geriatric" if age >= 65 else "adult"),
            "pregnancy": pregnancy, "pregnancy_trimester": preg_tri,
            "breastfeeding": breastfeeding,
            "hepatic_impairment": hep_imp, "liver_disease_type": hep_imp,
            "smoking_status": smoking, "alcohol_use": alcohol,
            "dialysis_status": dialysis,
            "comorbid": comorbid, "cv_history": cv_hist,
            "gi_risk": gi_risk, "high_risk_meds": hi_meds,
            "allergy_history": allergy,
        }
        labs = {
            "creatinine": creatinine if creatinine > 0 else None,
            "egfr":       egfr       if egfr       > 0 else None,
            "alt":        alt        if alt         > 0 else None,
            "hemoglobin": hemoglobin if hemoglobin  > 0 else None,
        }

        all_results = {}
        for drug_name in selected_drugs:
            drug_data = get_drug_data(cdss_data, drug_name)
            if drug_data:
                all_results[drug_name] = {
                    "alerts":    evaluate_drug(patient, labs, drug_data),
                    "drug_data": drug_data,
                }

        st.session_state["cdss_last_result"] = all_results
        st.session_state["cdss_last_patient"] = patient
        st.session_state["cdss_last_labs"]    = labs

    # Display results
    all_results = st.session_state.get("cdss_last_result", {})
    patient     = st.session_state.get("cdss_last_patient", {})
    labs        = st.session_state.get("cdss_last_labs", {})

    if not all_results:
        st.warning("No drugs selected.")
        return

    st.divider()

    # Patient summary bar
    age_grp = patient.get("age_group","adult")
    st.markdown(f"""
    <div style="background:#eaf2ff;border-left:4px solid #1a5276;padding:10px 16px;
    border-radius:0 8px 8px 0;margin-bottom:16px;font-size:13px">
    👤 <b>{patient.get('gender','')} · {patient.get('age','')} yrs · {patient.get('weight','')} kg · {age_grp.title()}</b>
    &nbsp;|&nbsp; Pregnancy: <b>{patient.get('pregnancy','No')}</b>
    &nbsp;|&nbsp; Breastfeeding: <b>{patient.get('breastfeeding','No')}</b>
    &nbsp;|&nbsp; Hepatic: <b>{patient.get('hepatic_impairment','None')}</b>
    &nbsp;|&nbsp; eGFR: <b>{labs.get('egfr') or 'N/A'}</b>
    </div>
    """, unsafe_allow_html=True)

    # One tab per drug
    if len(all_results) > 1:
        tabs = st.tabs([f"💊 {name}" for name in all_results])
    else:
        tabs = [st.container()]

    for tab, (drug_name, result) in zip(tabs, all_results.items()):
        with tab:
            alerts    = result["alerts"]
            drug_data = result["drug_data"]

            # Overall severity badge
            top_sev = alerts[0]["severity"] if alerts else "INFO"
            col_sev, col_info = st.columns([1, 3])
            with col_sev:
                color = SEVERITY_COLORS.get(top_sev,"#888")
                icon  = SEVERITY_ICONS.get(top_sev,"")
                st.markdown(f"""
                <div style="background:{color};color:white;padding:12px;border-radius:8px;
                text-align:center;font-weight:bold;font-size:14px">
                {icon} {top_sev}<br/><span style="font-size:11px">Highest Alert</span>
                </div>""", unsafe_allow_html=True)
            with col_info:
                st.markdown(f"**{drug_name}** · {drug_data.get('dose_value','')} {drug_data.get('dose_unit','')} · "
                            f"{drug_data.get('route','').title()} · {drug_data.get('freq','')} · "
                            f"{drug_data.get('duration_value','')} {drug_data.get('duration_unit','')}")
                counts = {}
                for a in alerts:
                    s = a["severity"]
                    counts[s] = counts.get(s,0) + 1
                badge_html = " ".join(
                    f'<span style="background:{SEVERITY_COLORS[s]};color:white;'
                    f'padding:2px 8px;border-radius:4px;font-size:11px;font-weight:bold">'
                    f'{SEVERITY_ICONS[s]} {c} {s}</span>'
                    for s, c in counts.items()
                )
                st.markdown(badge_html, unsafe_allow_html=True)

            st.divider()

            # Alerts by severity group
            for sev in SEVERITY_ORDER:
                sev_alerts = [a for a in alerts if a["severity"] == sev]
                if not sev_alerts:
                    continue
                color = SEVERITY_COLORS[sev]
                icon  = SEVERITY_ICONS[sev]
                label = f"{icon} {sev} ({len(sev_alerts)})"
                with st.expander(label, expanded=(sev in ("CONTRAINDICATED","HIGH"))):
                    for a in sev_alerts:
                        st.markdown(f"""
                        <div style="border-left:4px solid {color};padding:8px 12px;
                        margin:6px 0;background:#fafafa;border-radius:0 6px 6px 0">
                        <div style="font-size:11px;color:#666;margin-bottom:3px">
                        [{a['category']}]</div>
                        <div style="font-size:13px;color:#222">{a['message']}</div>
                        </div>""", unsafe_allow_html=True)

            st.divider()

            # Adverse Reactions
            with st.expander("📋 Adverse Reactions Reference", expanded=False):
                ar = drug_data.get("cdss_rules",{}).get("adverse_reactions",{})
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("**Common:**")
                    for r in ar.get("common",[]):
                        st.markdown(f"• {r}")
                with col2:
                    st.markdown("**Serious:**")
                    for r in ar.get("serious",[]):
                        st.markdown(f"• {r}")
                st.markdown("**System-wise:**")
                sw = ar.get("system_wise",{})
                for sys_name, effects in sw.items():
                    st.markdown(f"**{sys_name}:** {effects}")

            # Monitoring
            with st.expander("🔍 Monitoring Checklist", expanded=False):
                mon = drug_data.get("cdss_rules",{}).get("monitoring",{})
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.markdown("**Before Starting:**")
                    for m in mon.get("before_start",[]):
                        st.markdown(f"☐ {m}")
                with col2:
                    st.markdown("**During Treatment:**")
                    for m in mon.get("during_treatment",[]):
                        st.markdown(f"☐ {m}")
                with col3:
                    st.markdown("**Stop Drug If:**")
                    for m in mon.get("stop_if",[]):
                        st.markdown(f"🛑 {m}")


def _show_cdss_guide():
    with st.expander("ℹ️ How this CDSS works", expanded=True):
        st.markdown("""
**Step 1** — Fill in the patient profile above (age, gender, pregnancy, comorbidities, allergies, labs)

**Step 2** — Select one or more drugs from the dropdown

**Step 3** — Click **Evaluate Safety** → the system checks all clinical rules from the drug monography:

| Check | What it evaluates |
|---|---|
| 🚫 Contraindications | Allergy, pregnancy trimester, breastfeeding, CABG, severe organ impairment |
| ⚠️ High Alerts | CV risk, GI risk, renal impairment, geriatric, dose exceeded |
| 🔶 Moderate Alerts | Hepatic impairment, alcohol use, CDAD risk, pregnancy caution |
| ℹ️ Low Alerts | Smoking, mild considerations |
| ✅ Info | No alerts found |

**Currently loaded drugs:** Diclofenac, Amoxicillin
        """)
