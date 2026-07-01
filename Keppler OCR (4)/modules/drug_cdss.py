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

CDSS_JSON_PATH = Path(__file__).parent.parent / "datasets" / "diclofenac_amoxicillin_cdss.json"

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

def evaluate_trigger(trigger: str, env: dict) -> bool:
    import re
    expr = trigger
    expr = re.sub(r'\bOR\b', 'or', expr)
    expr = re.sub(r'\bAND\b', 'and', expr)
    
    def contains_replacer(match):
        var = match.group(1).strip()
        val = match.group(2).strip()
        return f"({val}.lower() in [str(item).lower() for item in {var}] if isinstance({var}, list) else {val}.lower() in str({var}).lower())"
        
    expr = re.sub(r'([a-zA-Z0-9_]+)\s+CONTAINS\s+(\'[^\']+\'|"[^"]+")', contains_replacer, expr)
    expr = re.sub(r'\bIN\b', 'in', expr)
    
    class SafeNone:
        def __lt__(self, other): return False
        def __le__(self, other): return False
        def __gt__(self, other): return False
        def __ge__(self, other): return False
        def __eq__(self, other): return other is None
        def __ne__(self, other): return other is not None
        def __str__(self): return ""
        def __bool__(self): return False
        def __contains__(self, other): return False
        
    safe_env = {k: (SafeNone() if v is None else v) for k, v in env.items()}
    
    try:
        return eval(expr, {"__builtins__": {}, "str": str, "isinstance": isinstance, "list": list}, safe_env)
    except Exception:
        return False

def evaluate_drug(patient: dict, labs: dict, drug_data: dict) -> list[dict]:
    alerts = []
    name = drug_data.get("name", "Drug")

    def add(severity, category, message, rule=""):
        alerts.append({
            "severity": severity,
            "category": category,
            "message":  message,
            "drug":     name,
            "rule":     rule,
        })

    # Prepare environment for triggers
    env = {
        'pregnancy': patient.get('pregnancy', 'No'),
        'pregnancy_trimester': patient.get('pregnancy_trimester', '').upper(),
        'gestational_age_weeks': patient.get('gestational_weeks', 0) or 0,
        'egfr': labs.get('egfr'),
        'crcl': labs.get('crcl'),
        'renal_impairment': patient.get('dialysis_status', 'None').capitalize(), # fallback
        'hepatic_impairment': patient.get('hepatic_impairment', 'None').capitalize(),
        'cv_history': patient.get('cv_history', []),
        'comorbid': patient.get('comorbid', []),
        'allergy_history': patient.get('allergy_history', []),
        'gi_risk': patient.get('gi_risk', []),
        'high_risk_meds': patient.get('high_risk_meds', []),
        'age': patient.get('age', 0),
        'alcohol_use': patient.get('alcohol_use', 'None').capitalize(),
        'smoking_status': patient.get('smoking_status', 'Non-smoker'),
        'alt': labs.get('alt'),
        'ast': labs.get('ast'),
        'hemoglobin': labs.get('hemoglobin'),
        'dialysis_status': patient.get('dialysis_status', 'None').capitalize(),
        'ULN': 40
    }
    
    # ── 1. BOX WARNING (always show) ─────────────────────────────────────────
    box_warnings = drug_data.get("box_warnings", [])
    for idx, bw in enumerate(box_warnings):
        add("HIGH", f"⬛ Box Warning: {bw.get('type', '')}", bw.get("description", ""), f"BW-{idx}")
        
    # ── 2. DYNAMIC CDSS ALERT RULES ─────────────────────────────────────────
    rules = drug_data.get("cdss_alert_rules", [])
    
    sev_map = {
        "CONTRAINDICATION": "CONTRAINDICATED",
        "ABSOLUTE": "CONTRAINDICATED",
        "MAJOR_INTERACTION": "HIGH",
        "WARNING": "HIGH",
        "MODERATE_INTERACTION": "MODERATE",
        "CAUTION": "MODERATE"
    }
    
    for r in rules:
        trigger_str = r.get("trigger", "")
        if evaluate_trigger(trigger_str, env):
            orig_sev = r.get("alert_type", "WARNING")
            mapped_sev = sev_map.get(orig_sev, "MODERATE")
            add(mapped_sev, f"Rule: {r.get('rule_id', '')}", r.get("message", ""), r.get("rule_id", ""))
            
    # ── 3. Sort by severity order ─────────────────────────────────────────────
    alerts.sort(key=lambda a: SEVERITY_ORDER.index(a["severity"])
                if a["severity"] in SEVERITY_ORDER else 99)

    # ── 4. If no alerts — add safe INFO ──────────────────────────────────────
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
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        pregnancy = st.selectbox("Pregnancy", ["No","Yes"], key="cdss_preg")
    with col2:
        preg_tri  = st.selectbox("Trimester (if pregnant)", ["NOT_APPLICABLE","first","second","third"], key="cdss_tri")
    with col3:
        if pregnancy == "Yes":
            gest_weeks = st.number_input("Gestational Age (weeks)", 1, 42, 20, key="cdss_gest")
        else:
            gest_weeks = None
    with col4:
        breastfeeding = st.selectbox("Breastfeeding", ["No","Yes"], key="cdss_bf")

    # Row 3: Comorbidities & Risk Factors
    st.markdown("**Comorbidities & Risk Factors**")
    col1, col2 = st.columns(2)
    with col1:
        comorbid_opts = ["hypertension","heart_disease","MI","stroke","heart_failure",
                         "diabetes","CKD","renal_disease","peptic_ulcer","GI_bleed",
                         "IBD","cirrhosis","hepatitis","COPD","asthma","immunocompromised",
                         "infectious_mononucleosis", "phenylketonuria", "Phenylketonuria (PKU)", "lymphatic_leukaemia"]
        comorbid = st.multiselect("Comorbid Conditions", comorbid_opts, key="cdss_comorbid")

        cv_opts  = ["MI","stroke","heart_failure","ischemic_heart_disease","CABG"]
        cv_hist  = st.multiselect("CV History", cv_opts, key="cdss_cv")
    with col2:
        gi_opts  = ["peptic_ulcer","GI_bleed","gastritis","IBD"]
        gi_risk  = st.multiselect("GI Risk Factors", gi_opts, key="cdss_gi")

        med_opts = ["anticoagulant","aspirin","steroid","SSRI","ACE_inhibitor",
                    "antibiotic_recent","methotrexate", "Warfarin"]
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
        creatinine = st.number_input("Creatinine (mg/dL)", 0.0, 20.0, 0.0, step=0.1, key="cdss_cr")
        potassium = st.number_input("Serum Potassium (mEq/L)", 0.0, 10.0, 0.0, step=0.1, key="cdss_k")
    with col2:
        egfr       = st.number_input("eGFR (mL/min)", 0.0, 200.0, 0.0, step=1.0, key="cdss_egfr")
        inr        = st.number_input("INR / Prothrombin Time", 0.0, 10.0, 0.0, step=0.1, key="cdss_inr")
    with col3:
        alt        = st.number_input("ALT (U/L)", 0.0, 2000.0, 0.0, step=1.0, key="cdss_alt")
        ast        = st.number_input("AST (U/L)", 0.0, 2000.0, 0.0, step=1.0, key="cdss_ast")
    with col4:
        hemoglobin = st.number_input("Haemoglobin (g/dL)", 0.0, 25.0, 0.0, step=0.1, key="cdss_hgb")

    # Row 6: Drug Selection
    st.markdown("### 💊 Drug Selection")
    selected_drugs = st.multiselect("Select Drug(s) to Evaluate", available_drugs,
                                    default=[available_drugs[0]] if available_drugs else [],
                                    key="cdss_drugs")
    
    drug_specifics = {}
    if selected_drugs:
        st.markdown("**Drug-Specific Details**")
        for drug in selected_drugs:
            st.markdown(f"*{drug}*")
            d_col1, d_col2, d_col3 = st.columns(3)
            with d_col1:
                route = st.selectbox("Route of Administration", ["oral", "parenteral", "topical", "ophthalmic", "rectal"], key=f"cdss_route_{drug}")
            with d_col2:
                indication = st.text_input("Primary Indication", key=f"cdss_ind_{drug}")
            with d_col3:
                duration = st.number_input("Duration of therapy (days)", 1, 365, 7, key=f"cdss_dur_{drug}")
            drug_specifics[drug] = {"route": route, "indication": indication, "duration": duration}

    st.markdown("<br>", unsafe_allow_html=True)
    run_btn = st.button("🔍 Evaluate Safety", type="primary", use_container_width=True)

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
            "pregnancy": pregnancy, "pregnancy_trimester": preg_tri, "gestational_weeks": gest_weeks,
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
            "ast":        ast        if ast         > 0 else None,
            "potassium":  potassium  if potassium   > 0 else None,
            "inr":        inr        if inr         > 0 else None,
            "hemoglobin": hemoglobin if hemoglobin  > 0 else None,
        }

        all_results = {}
        for drug_name in selected_drugs:
            drug_data = get_drug_data(cdss_data, drug_name)
            if drug_data:
                # Merge specifics if available
                specs = drug_specifics.get(drug_name, {})
                drug_data["route"] = specs.get("route", drug_data.get("route", ""))
                drug_data["indication"] = specs.get("indication", drug_data.get("indication", ""))
                drug_data["duration_value"] = specs.get("duration", drug_data.get("duration_value", ""))
                drug_data["duration_unit"] = "days"
                
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
