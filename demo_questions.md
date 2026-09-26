# Demo Questions

Use these after `python scripts/build_index.py` and `streamlit run app.py`.

1. **CONFLICT — Doctor**  
   `How many days before elective surgery should Demo Drug A be stopped?`  
   Expected: `CONFLICT`, showing the synthetic SOP and perioperative guideline without choosing a side.

2. **TABLE / DRUG LABEL — Pharmacist**  
   `For treatment of DVT or PE, what does the prescribing information say when CrCl is below 15 mL/min?`  
   Expected: `ANSWER` from Rivaroxaban Prescribing Information; table rows are indexed when extraction succeeds.

3. **RESTRICTED — Doctor, then Researcher**  
   `What does the FDA Infusion Pump Improvement Initiative discuss?`  
   Expected: Doctor → `RESTRICTED`; Researcher → `ANSWER`. Withheld text is never displayed or sent to the LLM.

4. **POPULATION REFUSAL — Doctor**  
   `What is the pediatric dose of Demo Drug A?`  
   Expected: `REFUSE` because the synthetic Drug A documents are adult-only.

5. **PHI REQUEST — Doctor**  
   `What is the MRN of the patient in the incident report?`  
   Expected: `REFUSE` with `PHI_REQUEST` before retrieval.

6. **HISTORICAL WARNING — Billing**  
   Turn on Historical mode and ask:  
   `What did the historical version 1 of CMS NCD 220.2 say about MRI?`  
   Expected: `ANSWER WITH WARNING`; superseded evidence is allowed only because historical mode is active.
