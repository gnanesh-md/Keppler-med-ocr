import json
import os

schema_path = '/home/aiuser/Downloads/Keppler OCR (4)/datasets/drug_cdss_schema.json'

with open(schema_path, 'r') as f:
    schema = json.load(f)

user_json_str = """{
  "drug": "Amoxicillin",
  "document_version": "Comprehensive Pin-to-Pin JSON — All Redline Headings & Conditions",

  "BOX_WARNING": {
    "heading": "BOX WARNING — HYPERSENSITIVITY REACTIONS",
    "severity": "CRITICAL / BLACK BOX",
    "description": "Serious and occasionally fatal hypersensitivity (Anaphylactoid) and Severe Cutaneous Adverse Reactions (SCAR) have been reported in patients receiving beta-lactam therapy, including Amoxicillin.",
    "cross_reference": "See: Special Warnings & Precautions"
  },

  "introduction": {
    "drug_class": "Broad-spectrum semisynthetic Aminopenicillin antibiotic",
    "activity": "Bactericidal",
    "primary_use": "Treatment of various bacterial infections",
    "mechanism_of_action": {
      "step_1": "Amoxicillin binds to Penicillin-binding proteins (PBPs) on the inner membrane of the bacterial cell wall.",
      "step_2": "Inactivation of PBPs interferes with cross-linkage of peptidoglycan chains.",
      "step_3": "Disrupts bacterial cell wall synthesis.",
      "result": "Weakening of cell wall and cell lysis."
    },
    "WHO_ATC_classification": {
      "Level_1": "J — Antiinfectives for systemic use",
      "Level_2": "J01 — Antibacterials for systemic use",
      "Level_3": "J01C — Beta-lactam antibacterials, Penicillins",
      "Level_4": "J01CA — Penicillins with extended spectrum",
      "Level_5": "J01CA04 — Amoxicillin"
    },
    "NOT_active_against": [
      "Pseudomonas aeruginosa",
      "Indole-positive Proteus species",
      "Serratia marcescens",
      "Klebsiella species",
      "Enterobacter species"
    ]
  },

  "indications": {
    "adults_and_pediatrics": {
      "upper_respiratory_tract_infections": {
        "body_parts": "Ear, Nose, Throat",
        "organisms": [
          "Streptococcus species (α- and β-hemolytic, β-lactamase–negative only)",
          "Streptococcus pneumoniae",
          "Staphylococcus spp.",
          "Haemophilus influenzae"
        ]
      },
      "lower_respiratory_tract_infections": {
        "organisms": [
          "Streptococcus spp. (α- and β-hemolytic, β-lactamase–negative only)",
          "S. pneumoniae",
          "Staphylococcus spp.",
          "H. influenzae"
        ]
      },
      "genitourinary_tract_infections": {
        "types": "Complicated and uncomplicated, acute and chronic",
        "organisms": [
          "Escherichia coli",
          "Proteus mirabilis",
          "Enterococcus faecalis"
        ]
      },
      "skin_and_skin_structure_infections": {
        "organisms": [
          "Streptococcus spp. (α- and β-hemolytic, β-lactamase–negative only)",
          "Staphylococcus spp.",
          "E. coli"
        ]
      },
      "tonsillitis_and_pharyngitis": {
        "population": "Adults and pediatric patients 12 years and older",
        "organism": "Streptococcus pyogenes (S. pyogenes)"
      },
      "septicaemia": {
        "organisms": [
          "H. influenzae",
          "E. coli",
          "P. mirabilis",
          "Streptococcus",
          "Streptococcus pneumoniae",
          "Streptococcus faecalis",
          "Salmonella typhi"
        ]
      },
      "gonorrhoea": {
        "organism": "Non-penicillinase-producing N. gonorrhoeae"
      },
      "prophylaxis": {
        "pre_dental_surgery": {
          "target": "Alpha-hemolytic (Viridans group) Streptococci",
          "use_case": "Before dental, oral or upper respiratory tract surgery/instrumentation"
        },
        "bacterial_endocarditis": {
          "conditions_requiring_prophylaxis": [
            "Congenital cardiac malformations",
            "Rheumatic and other acquired valvular lesions",
            "Prosthetic heart valves",
            "Previous history of bacterial Endocarditis",
            "Hypertrophic cardiomyopathy",
            "Surgically constructed systemic pulmonary shunts",
            "Mitral valve prolapse with valvular regurgitation",
            "Mitral valve prolapse without valvular regurgitation but with thickening/redundancy of valve leaflets"
          ]
        }
      }
    },
    "adults_only": {
      "H_pylori_infection_and_duodenal_ulcer": {
        "type": "Active or 1-year history of duodenal ulcer",
        "therapy_options": {
          "triple_therapy": "With Clarithromycin and Lansoprazole",
          "dual_therapy": "With Lansoprazole (for patients allergic/intolerant to Clarithromycin or known/suspected Clarithromycin resistance)"
        }
      }
    }
  },

  "dosage_forms_routes_strengths": {
    "oral": {
      "tablet": ["125 mg", "250 mg", "500 mg", "750 mg", "1000 mg"],
      "capsule": ["250 mg", "500 mg"],
      "oral_suspension": ["100 mg/mL", "125 mg/5 mL", "200 mg/5 mL", "250 mg/5 mL", "400 mg/5 mL"]
    },
    "parenteral": {
      "powder_for_solution_for_injection": ["250 mg", "500 mg", "1000 mg"]
    }
  },

  "dosage_and_administration": {
    "general_note": "Dosage must be individualized.",
    "ORAL": {
      "adults_and_pediatrics_over_40kg_3months_plus": {
        "upper_respiratory_tract_skin_genitourinary": {
          "mild_to_moderate": "500 mg every 12 hours OR 250 mg every 8 hours",
          "severe": "500 mg every 8 hours"
        },
        "lower_respiratory_tract": {
          "mild_moderate_severe": "875 mg every 12 hours OR 500 mg every 8 hours"
        }
      },
      "pediatrics_under_40kg_3months_plus": {
        "upper_respiratory_tract_skin_genitourinary": {
          "mild_to_moderate": "25 mg/kg/day divided every 12 hours OR 20 mg/kg/day divided every 8 hours",
          "severe": "45 mg/kg/day divided every 12 hours OR 40 mg/kg/day divided every 8 hours"
        },
        "lower_respiratory_tract": {
          "mild_moderate_severe": "45 mg/kg/day divided every 12 hours OR 40 mg/kg/day divided every 8 hours"
        }
      },
      "tonsillitis_pharyngitis_12years_plus": {
        "dose": "775 mg once daily within 1 hour after meal",
        "duration": "10 days"
      },
      "H_pylori_adults_only": {
        "triple_therapy": {
          "amoxicillin": "1000 mg",
          "clarithromycin": "500 mg",
          "lansoprazole": "30 mg",
          "frequency": "All twice daily (every 12 hours)",
          "duration": "14 days"
        },
        "dual_therapy": {
          "amoxicillin": "1000 mg",
          "lansoprazole": "30 mg",
          "frequency": "Each 3 times daily (every 8 hours)",
          "duration": "14 days"
        }
      },
      "endocarditis_prevention": {
        "adults": "3 g orally 1 hour before procedure; then 1.5 g 6 hours after initial dose",
        "pediatrics": "50 mg/kg (not to exceed adult dose) 1 hour before procedure; then 25 mg/kg 6 hours after initial dose"
      }
    },
    "PARENTERAL": {
      "adults_over_40kg": {
        "upper_respiratory_genitourinary_skin": "250 mg every 6–8 hours depending on condition",
        "lower_respiratory": "500 mg every 6–8 hours"
      },
      "pediatrics_under_40kg_over_3months": {
        "upper_respiratory_skin_genitourinary": {
          "children_under_20kg": "20 mg/kg/day in equally divided doses every 6–8 hours"
        },
        "lower_respiratory": {
          "children_under_20kg": "40 mg/kg/day equally divided every 6–8 hours"
        }
      },
      "bacterial_septicaemia": {
        "adults": "1000 mg every 6 hours by slow IV injection (3–4 min direct or via drip tube) or IV infusion over 30 min to 1 hour",
        "pediatrics": "20–40 mg/kg every 6 hours"
      }
    },
    "RENAL_IMPAIRMENT": {
      "adults_and_pediatrics_over_40kg_over_3months": {
        "GFR_over_30_mL_min": "No dose adjustment required",
        "GFR_10_to_30_mL_min": {
          "oral": "500 mg or 250 mg every 12 hours (depending on infection severity)",
          "IV": "1 g initially, then 0.5–1 g every 12–24 hours"
        },
        "GFR_less_than_10_mL_min": {
          "oral": "500 mg or 250 mg every 24 hours (depending on infection severity)",
          "IV_general": "1 g initially, then 0.5–1 g every 24 hours",
          "IV_E_coli_S_faecalis": "1 g every 12 hours"
        }
      },
      "hemodialysis": {
        "oral": "500 mg or 250 mg every 24 hours; additional dose both DURING and AT END of dialysis",
        "parenteral": "1 g at end of dialysis, then 0.5–1 g every 12–24 hours IV"
      },
      "pediatrics_under_12_weeks": {
        "oral_only": "Maximum 30 mg/kg/day divided every 12 hours (due to incompletely developed renal function)"
      }
    },
    "drug_administration_instructions": [
      "Take orally at the start of a meal.",
      "For IV infusion, dilute to 3% w/v concentration using: Normal Saline (0.9%), Ringer's solution, M/6 Sodium lactate, Hartmann's solution, Glucose 5%, or Sodium chloride 0.18% + Glucose 4%.",
      "Treat Streptococcus pyogenes infections for at least 10 days to prevent acute rheumatic fever.",
      "Continue treatment for minimum 48–72 hours beyond the time the patient becomes asymptomatic or bacterial eradication is confirmed."
    ],
    "oral_suspension_reconstitution": {
      "125mg_5mL": [
        {"bottle_size": "75 mL", "water_required": "52 mL"},
        {"bottle_size": "100 mL", "water_required": "70 mL"},
        {"bottle_size": "100 mL (alt)", "water_required": "103 mL"}
      ],
      "200mg_5mL": [
        {"bottle_size": "50 mL", "water_required": "39 mL"},
        {"bottle_size": "75 mL", "water_required": "57 mL"},
        {"bottle_size": "100 mL", "water_required": "76 mL"}
      ],
      "250mg_5mL": [
        {"bottle_size": "75 mL", "water_required": "51 mL"},
        {"bottle_size": "100 mL", "water_required": "68 mL"},
        {"bottle_size": "100 mL (alt)", "water_required": "101 mL"}
      ],
      "400mg_5mL": [
        {"bottle_size": "50 mL", "water_required": "36 mL"},
        {"bottle_size": "75 mL", "water_required": "54 mL"},
        {"bottle_size": "100 mL", "water_required": "71 mL"}
      ]
    }
  },

  "contraindications": [
    {
      "condition": "Known serious hypersensitivity to Amoxicillin or other β-lactam drugs",
      "examples": "Penicillins, Cephalosporins, Carbapenem, Monobactam",
      "reactions_include": "Anaphylaxis, Stevens-Johnson Syndrome"
    },
    {
      "condition": "Suspected or confirmed Infectious Mononucleosis",
      "reason": "High risk of erythematous skin rash"
    },
    {
      "condition": "Trivial or non-bacterial infections",
      "reason": "Antibiotics have no place in trivial infections"
    }
  ],

  "REDLINE_SPECIAL_WARNINGS_AND_PRECAUTIONS": {
    "heading": "SPECIAL WARNINGS & PRECAUTIONS — ALL CONDITIONS",

    "WARNING_1_ANAPHYLACTIC_REACTIONS": {
      "severity": "CRITICAL — POTENTIALLY FATAL",
      "title": "Anaphylactic / Hypersensitivity Reactions",
      "conditions": [
        "Serious and occasionally fatal hypersensitivity (anaphylactic) reactions reported in patients on Penicillin/Amoxicillin therapy.",
        "Anaphylaxis is more frequent with parenteral therapy but also occurs with oral Penicillins.",
        "Patients with history of Penicillin hypersensitivity may experience severe reactions with Cephalosporins.",
        "Allergic diathesis, Bronchial Asthma, and Hay Fever — special caution required.",
        "Drug-induced Enterocolitis Syndrome (DIES) reported mainly in children: protracted vomiting 1–4 hours after administration, abdominal pain, diarrhoea, hypotension, leukocytosis with neutrophilia; severe cases can progress to shock."
      ],
      "action_required": [
        "Careful inquiry about previous hypersensitivity to Penicillins, Cephalosporins, or other allergens before initiating therapy.",
        "DISCONTINUE Amoxicillin immediately if allergic reaction occurs.",
        "Serious anaphylactic reactions require: Epinephrine (immediate), IV steroids, Oxygen, Airway management including intubation."
      ]
    },

    "WARNING_2_SEVERE_CUTANEOUS_ADVERSE_REACTIONS": {
      "severity": "CRITICAL — REDLINE",
      "title": "Severe Cutaneous Adverse Reactions (SCAR)",
      "conditions_included": [
        "Stevens-Johnson Syndrome (SJS)",
        "Toxic Epidermal Necrolysis (TEN)",
        "Drug Reaction with Eosinophilia and Systemic Symptoms (DRESS)",
        "Acute Generalized Exanthematous Pustulosis (AGEP)"
      ],
      "action_required": [
        "Monitor patients closely if skin rash develops.",
        "DISCONTINUE Amoxicillin if lesions progress."
      ]
    },

    "WARNING_3_SKIN_RASH_MONONUCLEOSIS": {
      "severity": "HIGH",
      "title": "Skin Rash in Patients with Mononucleosis",
      "condition": "High percentage of patients with mononucleosis develop erythematous skin rash if given Amoxicillin.",
      "action_required": "DO NOT administer Amoxicillin to patients with mononucleosis."
    },

    "WARNING_4_CDAD": {
      "severity": "HIGH — POTENTIALLY FATAL",
      "title": "Clostridioides Difficile-Associated Diarrhea (CDAD)",
      "conditions": [
        "CDAD reported with use of nearly all antibacterial agents including Amoxicillin.",
        "Severity range: mild diarrhoea → fatal colitis."
      ],
      "action_required": "Consider CDAD diagnosis in patients with diarrhoea during or after antibiotic use."
    },

    "WARNING_5_PHENYLKETONURICS": {
      "severity": "MODERATE",
      "title": "Phenylketonurics",
      "conditions": [
        "Some Amoxicillin formulations contain Aspartame, which contains Phenylalanine — AVOID in Phenylketonurics.",
        "Oral suspension formulations do NOT contain Phenylalanine — SAFE for Phenylketonurics."
      ]
    },

    "WARNING_6_CARDIOVASCULAR_KOUNIS_SYNDROME": {
      "severity": "HIGH",
      "title": "Cardiovascular — Kounis Syndrome",
      "condition": "Kounis Syndrome (serious allergic reaction that can result in Myocardial Infarction) can occur as chest pain in association with an allergic reaction to Amoxicillin.",
      "action_required": "Recognize chest pain in the context of an allergic reaction as potentially Kounis Syndrome."
    },

    "WARNING_7_HEMATOLOGIC": {
      "severity": "MODERATE",
      "title": "Hematologic — Prolonged Prothrombin Time / Increased INR",
      "conditions": [
        "Abnormal prolongation of prothrombin time (increased INR) reported in patients on Amoxicillin AND oral anticoagulants."
      ],
      "action_required": [
        "Monitor INR appropriately.",
        "Adjust oral anticoagulant dose as necessary to maintain desired anticoagulation level.",
        "Cross-reference: Drug Interactions — Warfarin."
      ]
    },

    "WARNING_8_RENAL": {
      "severity": "MODERATE",
      "title": "Renal Impairment",
      "conditions": [
        "Amoxicillin is primarily excreted by the kidney.",
        "Patients with renal impairment require dose reduction proportional to the degree of renal function loss."
      ],
      "action_required": [
        "Periodic assessment of renal function during prolonged therapy.",
        "Cross-reference: Dosage and Administration — Renal Impairment."
      ]
    },

    "WARNING_9_PROLONGED_THERAPY": {
      "severity": "MODERATE",
      "title": "Prolonged Therapy Monitoring",
      "conditions": [
        "Elevated liver enzymes and blood count changes reported during prolonged use."
      ],
      "action_required": "Periodic assessment of renal, hepatic, and hematopoietic functions during prolonged therapy."
    },

    "WARNING_10_SUPERINFECTIONS": {
      "severity": "MODERATE",
      "title": "Superinfections",
      "conditions": [
        "Superinfections with mycotic or bacterial pathogens can occur (commonly Aerobacter, Pseudomonas, Candida)."
      ],
      "action_required": "DISCONTINUE Amoxicillin and institute appropriate therapy if superinfection occurs."
    },

    "WARNING_11_LYMPHATIC_LEUKAEMIA": {
      "severity": "MODERATE",
      "title": "Lymphatic Leukaemia",
      "condition": "Patients with Lymphatic Leukaemia are susceptible to Amoxicillin-induced skin rashes.",
      "action_required": "Give Amoxicillin with caution in these patients."
    },

    "WARNING_12_NON_SUSCEPTIBLE_MICROORGANISMS": {
      "severity": "MODERATE",
      "title": "Non-Susceptible Microorganisms",
      "conditions": [
        "Not suitable for infections unless pathogen is documented susceptible or highly likely to be susceptible.",
        "Particularly important for: Urinary tract infections, Severe ENT infections.",
        "Amoxicillin is NOT the treatment of choice for sore throat/pharyngitis due to possible underlying infectious mononucleosis."
      ]
    },

    "WARNING_13_CONVULSIONS": {
      "severity": "MODERATE",
      "title": "Convulsions",
      "conditions": [
        "Convulsions may occur in patients with impaired renal function.",
        "Convulsions may occur at high doses.",
        "Predisposing factors: history of seizures, treated epilepsy, meningeal disorders."
      ],
      "action_required": "Cross-reference: Adverse Reactions."
    },

    "WARNING_14_JARISCH_HERXHEIMER_REACTION": {
      "severity": "LOW",
      "title": "Jarisch-Herxheimer Reaction",
      "condition": "Seen following Amoxicillin treatment of Lyme disease — results from bactericidal activity on Borrelia burgdorferi spirochaete.",
      "action_required": "Reassure patients that this is common and usually self-limiting."
    },

    "WARNING_15_CRYSTALLURIA": {
      "severity": "LOW",
      "title": "Crystalluria",
      "conditions": [
        "Observed very rarely in patients with reduced urine output, predominantly with parenteral therapy.",
        "High urinary Amoxicillin concentrations can cause precipitation in urinary catheters."
      ],
      "action_required": [
        "Visually inspect catheters at intervals.",
        "At high doses: maintain adequate fluid intake and urinary output."
      ]
    },

    "WARNING_16_PAEDIATRIC_USE": {
      "severity": "MODERATE",
      "title": "Paediatric Use — Neonates and Premature Children",
      "conditions": [
        "Precaution required in premature children and during neonatal period.",
        "Elimination of Amoxicillin may be delayed due to incompletely developed renal function in neonates/young infants."
      ],
      "action_required": [
        "Monitor renal, hepatic, and haematological functions.",
        "Modify dosing in pediatric patients 12 weeks or younger."
      ]
    },

    "WARNING_17_EFFECTS_ON_LABORATORY_TESTS": {
      "severity": "LOW",
      "title": "Effects on Laboratory Tests",
      "conditions": [
        "Amoxicillin may decrease urinary estriol in pregnant women.",
        "High urine concentrations of Ampicillin may cause false-positive reactions for urinary glucose (colorimetric methods).",
        "Amoxicillin may interfere with protein testing (colorimetric methods).",
        "Transient decrease in plasma concentration of: total conjugated estriol, estriol-glucuronide, conjugated estrone, Estradiol — following administration in pregnant women."
      ]
    }
  },

  "adverse_reactions": {
    "clinically_significant": [
      "Anaphylactic reactions",
      "Severe Cutaneous Adverse Reactions (SCAR)",
      "Clostridioides difficile-associated Diarrhoea (CDAD)"
    ],
    "common": [
      "Diarrhoea",
      "Rash",
      "Vomiting",
      "Nausea",
      "Abdominal pain",
      "Headache",
      "Vulvovaginal mycotic infection",
      "Candidiasis",
      "Fungal/Mycotic infection"
    ],
    "frequency_not_known": [
      "Kounis syndrome",
      "Pain at intramuscular injection site",
      "Phlebitis at IV injection site",
      "Interstitial nephritis (Oliguria, Proteinuria, Haematuria, Hyaline casts, Pyuria)",
      "Nephropathy"
    ],
    "post_marketing": {
      "infections_and_infestations": ["Mucocutaneous candidiasis"],
      "gastrointestinal": ["Black hairy tongue", "Haemorrhagic/Pseudomembranous colitis"],
      "immune": [
        "Hypersensitivity reactions",
        "Anaphylactic/anaphylactoid reactions including shock",
        "Angioedema",
        "Serum sickness-like reactions",
        "Hypersensitivity vasculitis"
      ],
      "skin_and_appendages": [
        "Rashes", "Pruritus", "Urticaria", "Erythema multiforme",
        "Stevens-Johnson Syndrome (SJS)", "Toxic Epidermal Necrolysis (TEN)",
        "DRESS", "AGEP", "Exfoliative dermatitis"
      ],
      "hepatic": [
        "Moderate rise in AST and/or ALT",
        "Hepatic dysfunction",
        "Cholestatic jaundice",
        "Hepatic cholestasis",
        "Acute cytolytic hepatitis"
      ],
      "renal": ["Crystalluria"],
      "central_nervous_system": [
        "Reversible hyperactivity",
        "Agitation", "Anxiety", "Insomnia", "Confusion",
        "Convulsions", "Behavioural changes", "Aseptic meningitis", "Dizziness"
      ],
      "hemic_and_lymphatic": [
        "Anaemia including Haemolytic anaemia",
        "Thrombocytopenia",
        "Thrombocytopenic purpura",
        "Eosinophilia",
        "Leukopenia",
        "Agranulocytosis"
      ],
      "miscellaneous": ["Tooth discoloration (brown, yellow, or gray staining)"]
    },
    "reporting": "Report adverse events immediately to the nearby ADR monitoring centre to PvPI (toll-free: 1800 180 3024)"
  },

  "drug_drug_interactions": [
    {
      "drug_or_class": "Probenecid",
      "interaction": "Decreases renal tubular secretion of Amoxicillin → increased and prolonged blood levels of Amoxicillin",
      "clinical_comment": "Caution recommended"
    },
    {
      "drug_or_class": "Oral Anticoagulants (e.g., Warfarin)",
      "interaction": "Abnormal prolongation of prothrombin time (increased INR)",
      "clinical_comment": "Dose adjustment of oral anticoagulants may be necessary"
    },
    {
      "drug_or_class": "Allopurinol",
      "interaction": "Concurrent use increases incidence of rashes",
      "clinical_comment": "Caution recommended"
    },
    {
      "drug_or_class": "Oral Contraceptives",
      "interaction": "Amoxicillin may affect intestinal flora → lower estrogen reabsorption → reduced efficacy of combined oral estrogen/progesterone contraceptives",
      "clinical_comment": "Caution recommended"
    },
    {
      "drug_or_class": "Other Antibacterials (Chloramphenicol, Macrolides, Sulfonamides, Tetracyclines)",
      "interaction": "May interfere with the bactericidal effects of Penicillin",
      "clinical_comment": "Caution recommended"
    },
    {
      "drug_or_class": "Methotrexate",
      "interaction": "Penicillins compete with renal tubular secretion of Methotrexate → decreased clearance → increased Methotrexate serum concentrations and increased toxicity risk",
      "clinical_comment": "Closely monitor serum Methotrexate levels"
    },
    {
      "drug_or_class": "Digoxin",
      "interaction": "Increased absorption of Digoxin possible",
      "clinical_comment": "Dose adjustment of Digoxin may be necessary"
    },
    {
      "drug_or_class": "Forced Diuresis",
      "interaction": "Leads to reduction in blood concentrations of Amoxicillin by increased elimination",
      "clinical_comment": "Caution recommended when given concomitantly"
    },
    {
      "drug_or_class": "Estriol",
      "interaction": "Amoxicillin may decrease the amount of urinary Estriol in pregnant women",
      "clinical_comment": "Caution recommended when given concomitantly"
    }
  ],

  "drug_laboratory_test_interactions": [
    "May interfere with protein testing when colorimetric methods are used",
    "May cause false-positive reactions for presence of glucose in urine",
    "Following administration in pregnant women: transient decrease in plasma concentration of total conjugated estriol, estriol-glucuronide, conjugated estrone, and Estradiol"
  ],

  "use_in_special_populations": {
    "pregnancy": {
      "oral": {
        "USFDA_category": "B",
        "note": "No adequate and well-controlled studies in pregnant women. Use only if clearly needed."
      },
      "parenteral": {
        "note": "Amoxicillin diffuses across the placenta into fetal circulation. Use when potential benefits outweigh potential risks."
      }
    },
    "lactation": {
      "note": "Penicillins are excreted in human milk. May lead to sensitization of infants.",
      "action": [
        "Exercise caution when administered to lactating women.",
        "STOP breastfeeding if gastrointestinal disorders (diarrhoea, candidosis, or skin rash) occur in the newborn."
      ]
    },
    "pediatrics": {
      "established_uses": [
        "Upper respiratory tract infections",
        "Genitourinary tract infections",
        "Skin and skin structure infections",
        "Lower respiratory tract infections"
      ],
      "NOT_established": [
        "H. pylori infection",
        "Tonsillitis/Pharyngitis in children younger than 12 years"
      ],
      "neonates_warning": "Elimination may be delayed due to incompletely developed renal function; modify dosing in patients ≤12 weeks of age."
    },
    "geriatrics": {
      "note": "No identified differences in response between elderly (≥65 years) and younger patients, but greater sensitivity cannot be ruled out.",
      "renal_risk": "Drug substantially excreted by kidney; risk of toxic reactions greater with impaired renal function.",
      "action": "Monitor renal function; care in dose selection."
    },
    "renal_impairment": {
      "note": "Primarily eliminated by kidney; dose adjustment required for GFR < 30 mL/min.",
      "cross_reference": "See Dosage and Administration — Renal Impairment"
    }
  },

  "pharmaceutical_information": {
    "amoxicillin_base": {
      "INN": "amoxicillin",
      "chemical_name": "(2S,5R,6R)-6-[[(2R)-2-amino-2-(4-hydroxyphenyl)acetyl]amino]-3,3-dimethyl-7-oxo-4-thia-1-azabicyclo[3.2.0]heptane-2-carboxylic acid",
      "molecular_formula": "C16H19N3O5S",
      "molecular_weight": "365.4 g/mol",
      "physical_description": "Off-white solid",
      "melting_point": "194°C",
      "solubility": "Soluble in water"
    },
    "amoxicillin_trihydrate": {
      "chemical_name": "(2S,5R,6R)-6-[[(2R)-2-amino-2-(4-hydroxyphenyl)acetyl]amino]-3,3-dimethyl-7-oxo-4-thia-1-azabicyclo[3.2.0]heptane-2-carboxylic acid; trihydrate",
      "molecular_formula": "C16H19N3O5S.3H2O",
      "molecular_weight": "419.5 g/mol",
      "physical_description": "White or almost white crystalline powder",
      "solubility": "Insoluble in water; readily soluble in phosphate buffer"
    },
    "amoxicillin_sodium": {
      "chemical_name": "Sodium (2S,5R,6R)-6-[[(2R)-2-amino-2-(4-hydroxyphenyl)acetyl]amino]-3,3-dimethyl-7-oxo-4-thia-1-azabicyclo[3.2.0]heptane-2-carboxylate",
      "molecular_formula": "C16H18N3NaO5S",
      "molecular_weight": "387.4 g/mol"
    }
  }
}"""

user_data = json.loads(user_json_str)

cdss_rules = {
    "box_warning": {
        "hypersensitivity": user_data.get("BOX_WARNING", {}).get("description", "Serious hypersensitivity reported.")
    },
    "contraindications": {
        "hypersensitivity": user_data["contraindications"][0]["condition"],
        "mononucleosis": user_data["contraindications"][1]["condition"],
        "trivial_infections": user_data["contraindications"][2]["condition"]
    },
    "warnings_by_condition": {
        "pregnancy": {
            "trigger_fields": ["pregnancy"],
            "trigger_values": ["Yes"],
            "severity": "LOW",
            "message": "FDA Category B — Use only if clearly needed. " + user_data["use_in_special_populations"]["pregnancy"]["oral"]["note"]
        },
        "breastfeeding": {
            "trigger_fields": ["breastfeeding"],
            "trigger_values": ["Yes"],
            "severity": "MODERATE",
            "message": user_data["use_in_special_populations"]["lactation"]["note"] + " " + " ".join(user_data["use_in_special_populations"]["lactation"]["action"])
        },
        "cdad_risk": {
            "trigger_fields": ["comorbid", "high_risk_meds"],
            "trigger_values": ["immunocompromised","previous_cdiff","antibiotic_recent"],
            "severity": "HIGH",
            "message": "WARNING: " + " ".join(user_data["REDLINE_SPECIAL_WARNINGS_AND_PRECAUTIONS"]["WARNING_4_CDAD"]["conditions"])
        },
        "renal_risk": {
            "trigger_fields": ["labs", "comorbid", "dialysis_status"],
            "trigger_values": ["renal_disease","CKD","dialysis"],
            "severity": "MODERATE",
            "message": " ".join(user_data["REDLINE_SPECIAL_WARNINGS_AND_PRECAUTIONS"]["WARNING_8_RENAL"]["conditions"])
        },
        "geriatric": {
            "trigger_fields": ["age"],
            "age_threshold": 65,
            "severity": "LOW",
            "message": user_data["use_in_special_populations"]["geriatrics"]["note"]
        },
        "mononucleosis_rash": {
            "title": "Mononucleosis",
            "trigger_values": ["infectious_mononucleosis", "mononucleosis"],
            "severity": "HIGH",
            "message": user_data["REDLINE_SPECIAL_WARNINGS_AND_PRECAUTIONS"]["WARNING_3_SKIN_RASH_MONONUCLEOSIS"]["condition"] + " Action: " + user_data["REDLINE_SPECIAL_WARNINGS_AND_PRECAUTIONS"]["WARNING_3_SKIN_RASH_MONONUCLEOSIS"]["action_required"]
        },
        "phenylketonuria": {
            "title": "Phenylketonuria",
            "trigger_values": ["phenylketonuria", "pku"],
            "severity": "MODERATE",
            "message": " ".join(user_data["REDLINE_SPECIAL_WARNINGS_AND_PRECAUTIONS"]["WARNING_5_PHENYLKETONURICS"]["conditions"])
        },
        "leukaemia": {
            "title": "Lymphatic Leukaemia",
            "trigger_values": ["lymphatic_leukaemia", "leukaemia"],
            "severity": "MODERATE",
            "message": user_data["REDLINE_SPECIAL_WARNINGS_AND_PRECAUTIONS"]["WARNING_11_LYMPHATIC_LEUKAEMIA"]["condition"]
        },
        "anticoagulant_interaction": {
            "title": "Anticoagulant Interaction",
            "trigger_values": ["anticoagulant", "warfarin"],
            "severity": "MODERATE",
            "message": " ".join(user_data["REDLINE_SPECIAL_WARNINGS_AND_PRECAUTIONS"]["WARNING_7_HEMATOLOGIC"]["conditions"])
        },
        "kounis_syndrome": {
            "title": "Cardiovascular (Kounis Syndrome)",
            "trigger_values": ["kounis", "MI", "ischemic_heart_disease", "heart_disease"],
            "severity": "MODERATE",
            "message": user_data["REDLINE_SPECIAL_WARNINGS_AND_PRECAUTIONS"]["WARNING_6_CARDIOVASCULAR_KOUNIS_SYNDROME"]["condition"]
        }
    },
    "adverse_reactions": {
        "common": user_data["adverse_reactions"]["common"],
        "serious": user_data["adverse_reactions"]["clinically_significant"],
        "system_wise": {
             "Infections": ", ".join(user_data["adverse_reactions"]["post_marketing"].get("infections_and_infestations", [])),
             "GI": ", ".join(user_data["adverse_reactions"]["post_marketing"].get("gastrointestinal", [])),
             "Immune": ", ".join(user_data["adverse_reactions"]["post_marketing"].get("immune", [])),
             "Skin": ", ".join(user_data["adverse_reactions"]["post_marketing"].get("skin_and_appendages", [])),
             "Hepatic": ", ".join(user_data["adverse_reactions"]["post_marketing"].get("hepatic", [])),
             "Renal": ", ".join(user_data["adverse_reactions"]["post_marketing"].get("renal", [])),
             "CNS": ", ".join(user_data["adverse_reactions"]["post_marketing"].get("central_nervous_system", [])),
             "Haematologic": ", ".join(user_data["adverse_reactions"]["post_marketing"].get("hemic_and_lymphatic", []))
        }
    },
    "monitoring": {
        "before_start": ["Careful inquiry about previous hypersensitivity"],
        "during_treatment": ["Periodic assessment of renal, hepatic, and hematopoietic functions", "Monitor INR if on anticoagulants"],
        "stop_if": ["Allergic reaction occurs", "Lesions/rash progress", "Severe diarrhoea (CDAD)"]
    }
}

new_amox = {
    "name": "Amoxicillin",
    "route": "oral",
    "freq": "TDS",
    "duration_value": 7,
    "duration_unit": "days",
    "dose_value": 500,
    "dose_unit": "mg",
    
    "document_version": user_data["document_version"],
    "introduction": user_data["introduction"],
    "indications": user_data["indications"],
    "dosage_forms_routes_strengths": user_data["dosage_forms_routes_strengths"],
    "dosage_and_administration": user_data["dosage_and_administration"],
    "contraindications_raw": user_data["contraindications"],
    "REDLINE_SPECIAL_WARNINGS_AND_PRECAUTIONS": user_data["REDLINE_SPECIAL_WARNINGS_AND_PRECAUTIONS"],
    "drug_drug_interactions": user_data["drug_drug_interactions"],
    "use_in_special_populations": user_data["use_in_special_populations"],
    "pharmaceutical_information": user_data["pharmaceutical_information"],
    
    "cdss_rules": cdss_rules
}

schema["drugs"][1] = new_amox

with open(schema_path, 'w') as f:
    json.dump(schema, f, indent=2)

print("Schema updated successfully.")
