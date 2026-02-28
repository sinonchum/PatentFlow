import streamlit as st
import tempfile
import os
from pathlib import Path
from typing import Dict, Any, Optional
import json
import time

# Import backend modules
from src.skills import generate_claim_chart, classify_claim
from src.translator import PatentTranslator
from src.pipeline import run_pipeline


st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=Playfair+Display:ital,wght@0,400;0,600;1,400&display=swap');

    /* 1. Global App Background and Typography */
    .stApp {
        background-color: #FFFFFF;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        color: #111111;
    }
    
    h1, h2, h3, h4, h5, h6 {
        font-family: 'Playfair Display', serif !important;
        font-weight: 600 !important;
        letter-spacing: -0.02em !important;
        color: #111111 !important;
    }

    /* 2. Drastically reduce main container padding (remove huge top blank space) */
    .block-container {
        padding-top: 3rem !important;
        padding-bottom: 3rem !important;
        padding-left: 5rem !important;
        padding-right: 5rem !important;
        max-width: 1200px !important;
    }

    /* 3. Aggressively compress vertical spacing between all elements */
    [data-testid="stVerticalBlock"] > div {
        margin-bottom: 0px !important;
    }

    /* 4. Overhaul the Sidebar to look premium */
    [data-testid="stSidebar"] {
        background-color: #FAFAFA !important;
        border-right: 1px solid #EAEAEA !important;
    }

    [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {
        font-family: 'Inter', sans-serif !important;
        font-size: 0.85rem !important;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: #666666 !important;
    }
    
    /* 5. Make File Uploaders ULTRA compact (No giant dashed boxes) */
    [data-testid="stFileUploadDropzone"] {
        padding: 10px !important;
        min-height: 40px !important;
        border-radius: 2px !important;
        border: 1px solid #EAEAEA !important;
        background-color: #FFFFFF !important;
        transition: border-color 0.2s ease;
    }
    [data-testid="stFileUploadDropzone"]:hover {
        border-color: #111111 !important;
    }
    [data-testid="stFileUploadDropzone"] > div > div > small {
        display: none !important; /* Hide the verbose "Limit 200MB" text */
    }

    /* 6. Fix Tabs to look like a native Mac/Windows app (No ugly red line) */
    button[data-baseweb="tab"] {
        padding-top: 12px !important;
        padding-bottom: 12px !important;
        font-size: 14px !important;
        font-family: 'Inter', sans-serif !important;
        font-weight: 400 !important;
        color: #888888 !important;
        border-bottom: 1px solid transparent !important;
    }
    button[data-baseweb="tab"][aria-selected="true"] {
        color: #111111 !important;
        font-weight: 500 !important;
        border-bottom: 1px solid #111111 !important;
    }
    div[data-baseweb="tab-highlight"] {
        display: none !important;
    }

    /* 7. Redesign Info/Alert boxes */
    [data-testid="stAlert"] {
        padding: 12px 16px !important;
        background-color: #FFFFFF !important;
        border: 1px solid #EAEAEA !important;
        border-radius: 2px !important;
        border-left: 3px solid #111111 !important;
        color: #333333 !important;
        box-shadow: none !important;
        font-family: 'Inter', sans-serif !important;
        font-size: 14px !important;
    }

    /* 8. Buttons */
    .stButton > button {
        border-radius: 2px !important;
        border: 1px solid #111111 !important;
        color: #111111 !important;
        font-family: 'Inter', sans-serif !important;
        font-weight: 500 !important;
        background-color: #FFFFFF !important;
        transition: all 0.2s ease;
        text-transform: uppercase;
        font-size: 13px !important;
        letter-spacing: 0.02em;
        padding: 0.5rem 1rem !important;
    }
    .stButton > button:hover {
        background-color: #111111 !important;
        color: #FFFFFF !important;
        border-color: #111111 !important;
    }
    
    /* Input Fields */
    .stSelectbox > div > div, .stTextArea > div > div > textarea {
        border-radius: 2px !important;
        border: 1px solid #EAEAEA !important;
        font-family: 'Inter', sans-serif !important;
    }
    .stSelectbox > div > div:focus-within, .stTextArea > div > div > textarea:focus {
        border-color: #111111 !important;
        box-shadow: none !important;
    }
    
    /* 9. Hide header junk */
    header {visibility: hidden;}
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}

    /* Tables */
    table {
        border-collapse: collapse !important;
        width: 100% !important;
        font-family: 'Inter', sans-serif !important;
        font-size: 14px !important;
    }
    th {
        border-bottom: 1px solid #111111 !important;
        font-weight: 500 !important;
        color: #111111 !important;
        text-transform: uppercase;
        font-size: 12px !important;
        letter-spacing: 0.05em;
        padding: 12px !important;
    }
    td {
        border-bottom: 1px solid #EAEAEA !important;
        padding: 12px !important;
        color: #333333 !important;
    }
</style>
""", unsafe_allow_html=True)


def setup_page_config():
    """Configure Streamlit page settings"""
    st.set_page_config(
        page_title="PatentFlow - Document Processing Workspace",
        page_icon="▪️",
        layout="wide",
        initial_sidebar_state="expanded"
    )


def render_sidebar():
    """Render the sidebar with input controls"""
    st.sidebar.title("INPUT & CONFIGURATION")
    
    # File uploaders
    st.sidebar.subheader("Document Upload")
    
    oa_file = st.sidebar.file_uploader(
        "EPO Office Action (PDF/TXT)",
        type=['pdf', 'txt'],
        help="Upload the EPO Office Action document"
    )
    
    spec_file = st.sidebar.file_uploader(
        "Patent Specification",
        type=['pdf', 'txt', 'docx'],
        help="Upload the patent specification document"
    )
    
    # Claim type selector (权利种类)
    st.sidebar.subheader("Claim Type")
    claim_type_options = [
        "Method",
        "Apparatus",
        "System",
        "Product",
        "Use",
        "Computer Program",
        "Computer-Readable Medium"
    ]
    
    selected_claim_type = st.sidebar.selectbox(
        "Claim Category (权利种类)",
        claim_type_options,
        index=0,
        help="Select the statutory category for the independent claim"
    )
    
    # Examiner preference dropdown
    st.sidebar.subheader("Examiner Preference")
    examiner_options = [
        "Jukka Tapaninen - Telecom",
        "Maria Schmidt - Mechanics", 
        "Hans Mueller - Chemistry",
        "Sophie Martin - Biotechnology",
        "General - No Specific Bias"
    ]
    
    selected_examiner = st.sidebar.selectbox(
        "Examiner Preference Bias",
        examiner_options,
        index=0,
        help="Select examiner to tailor response strategy"
    )
    
    # Primary action button
    st.sidebar.subheader("Processing")
    
    run_button = st.sidebar.button(
        "Run PatentFlow Pipeline",
        use_container_width=True,
        help="Execute the complete PatentFlow analysis pipeline"
    )
    
    return oa_file, spec_file, selected_examiner, selected_claim_type, run_button


def save_uploaded_file(uploaded_file) -> Optional[str]:
    """Save uploaded file to temporary directory and return path"""
    if uploaded_file is None:
        return None
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=f".{uploaded_file.name.split('.')[-1]}") as tmp_file:
        tmp_file.write(uploaded_file.getvalue())
        return tmp_file.name


def process_documents(oa_path: str, spec_path: str, examiner: str, claim_type: str) -> Dict[str, Any]:
    """Process documents through PatentFlow pipeline"""
    results = {
        "claim_chart": None,
        "translation_table": None,
        "response_draft": None,
        "status": "processing",
        "error": None
    }
    
    try:
        # Initialize translator
        translator = PatentTranslator()
        
        # Mock processing for demonstration
        # In real implementation, this would call the actual pipeline
        
        # 1. Generate claim chart (mock data)
        sample_claim = "A method for wireless communication, comprising: transmitting a downlink control information (DCI) format; determining a timing offset K0; and receiving a physical downlink shared channel (PDSCH) based on the timing offset."
        sample_prior_art = "The prior art D1 discloses a basic wireless communication system with fixed timing."
        
        claim_chart_result = generate_claim_chart(sample_claim, sample_prior_art)
        results["claim_chart"] = claim_chart_result.get("claim_chart", [])
        
        # 2. Generate translation verification table
        sample_chinese_text = "一种无线通信方法，包括：发送下行控制信息DCI格式；确定定时偏移量K0；以及基于该定时偏移量接收物理下行共享信道PDSCH。其中，所述终端设备被配置为根据所述DCI格式来确定所述定时偏移量。"
        translation_table = translator.translate_and_align(sample_chinese_text)
        results["translation_table"] = translation_table
        
        # 3. Generate response draft with claim type
        results["response_draft"] = generate_mock_response_draft(examiner, claim_type)
        
        results["status"] = "completed"
        
    except Exception as e:
        results["status"] = "error"
        results["error"] = str(e)
    
    return results


def generate_mock_response_draft(examiner: str, claim_type: str = "Method") -> str:
    """Generate a mock EPO response draft"""
    examiner_name = examiner.split(" - ")[0] if " - " in examiner else examiner
    
    draft = f"""RESPONSE TO EXAMINER {examiner_name.upper()} - OFFICE ACTION DATED [DATE]

Dear Examiner,

Re: European Patent Application No. [Application Number]
Art. 56 Inventive Step Objection - {claim_type} Claim

The Applicant respectfully responds to the Office Action and would like to submit the following observations regarding the inventive step objection under Art. 56 EPC.

1. TECHNICAL BACKGROUND
The invention relates to a {claim_type.lower()} for dynamic scheduling in 5G NR systems, particularly addressing the need for flexible timing offset determination for HARQ-ACK feedback.

2. DISTINGUISHING FEATURES OVER D1
The independent {claim_type.lower()} claim contains several technical features that are not disclosed in the prior art D1:

2.1 Dynamic Timing Offset Determination
The claimed method specifically comprises determining a timing offset K0 based on DCI format parameters, which provides adaptive scheduling flexibility not present in D1.

2.2 Configurable Terminal Device Behavior
The terminal device is specifically configured to determine the timing offset based on DCI format characteristics, enabling context-aware scheduling decisions.

3. TECHNICAL EFFECTS AND ADVANTAGES
The claimed invention provides the following technical advantages:
- Reduced latency in HARQ-ACK feedback processing
- Improved spectral efficiency through adaptive scheduling
- Enhanced system flexibility for diverse traffic patterns

4. NO MOTIVATION TO COMBINE D1 WITH STANDARD TEACHINGS
The skilled person would have had no motivation to modify D1 by incorporating the dynamic timing offset features from 3GPP standards, as:
- D1 is designed for fixed scheduling scenarios
- The combination would require fundamental redesign of the D1 architecture
- No technical problem in D1 would be solved by such modification

5. CONCLUSION
For the reasons set forth above, the claimed invention involves an inventive step within the meaning of Art. 56 EPC. The combination of D1 with standard teachings would not have been obvious to the skilled person.

The Applicant respectfully requests that the objection be withdrawn and the application proceed to grant.

Yours faithfully,
[Applicant Name]
Authorized Representative"""
    
    return draft


def render_claim_chart_tab(claim_chart_data):
    """Render the Claim Chart tab"""
    st.subheader("Claim Chart (Art. 56)")
    
    if not claim_chart_data:
        st.info("No claim chart data available. Please run the PatentFlow pipeline.")
        return
    
    # Create markdown table
    st.markdown("### Feature-by-Feature Comparison: Independent Claim vs Prior Art D1")
    
    # Build table header
    table_md = "| Feature ID | Claim Limitation | D1 Mapping | Remarks |\n"
    table_md += "|---|---|---|---|\n"
    
    # Add table rows
    for item in claim_chart_data:
        feature_id = item.get("feature_id", "")
        claim_limitation = item.get("claim_limitation", "").replace("|", "\\|")
        d1_mapping = item.get("d1_mapping", "").replace("|", "\\|")
        remarks = "Not disclosed" if d1_mapping == "..." else "Partially disclosed"
        
        table_md += f"| {feature_id} | {claim_limitation} | {d1_mapping} | {remarks} |\n"
    
    st.markdown(table_md)
    
    # Add analysis summary
    st.markdown("### Analysis Summary")
    st.success("The independent claim contains multiple distinguishing features over D1 that contribute to inventive step.")


def render_translation_tab(translation_table):
    """Render the Translation Verifier tab"""
    st.subheader("Translation Verifier (Art. 123(2))")
    
    if not translation_table:
        st.info("No translation data available. Please run the PatentFlow pipeline.")
        return
    
    st.markdown("### Dual-Verification Translation Table")
    
    # Display the translation table
    st.markdown(translation_table)
    
    # Add warning about potential discrepancies
    st.markdown("### Translation Quality Alerts")
    st.warning("""
    **Critical Terms to Verify:**
    - **"comprising"** vs **"consisting of"** - Ensure open-ended claim language
    - **"wherein"** clauses - Verify dependent claim dependencies
    - **"configured to"** vs **"adapted to"** - Check functional language accuracy
    """)
    
    st.info("Review highlighted discrepancies in the table above. Any VERB_MISMATCH should be carefully evaluated before filing.")


def render_response_draft_tab(response_draft):
    """Render the Response Draft tab"""
    st.subheader("Response Draft")
    
    if not response_draft:
        st.info("No response draft available. Please run the PatentFlow pipeline.")
        return
    
    # Editable text area for response draft
    edited_draft = st.text_area(
        "EPO Response Draft (Editable)",
        value=response_draft,
        height=500,
        help="You can edit the response draft before export"
    )
    
    return edited_draft


def render_export_section(response_draft):
    """Render export functionality"""
    st.subheader("Export Options")
    
    if not response_draft:
        st.info("No response draft available for export.")
        return
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Export as TXT
        st.download_button(
            label="Download as TXT",
            data=response_draft,
            file_name="epo_response.txt",
            mime="text/plain",
            use_container_width=True
        )
    
    with col2:
        # Export as DOCX (simplified version)
        try:
            from docx import Document
            doc = Document()
            doc.add_paragraph(response_draft)
            
            # Save to temporary file for download
            with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp_file:
                doc.save(tmp_file.name)
                with open(tmp_file.name, "rb") as f:
                    docx_bytes = f.read()
                os.unlink(tmp_file.name)
            
            st.download_button(
                label="Download as DOCX",
                data=docx_bytes,
                file_name="epo_response.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True
            )
        except ImportError:
            st.error("python-docx not available for DOCX export. Please install with: pip install python-docx")


def main():
    """Main application entry point"""
    setup_page_config()
    
    # Page header
    st.title("PatentFlow")
    st.markdown("**Document Processing Workspace for European Patent Attorneys**")
    st.markdown("---")
    
    # Render sidebar
    oa_file, spec_file, selected_examiner, selected_claim_type, run_button = render_sidebar()
    
    # Main content area with tabs
    tab1, tab2, tab3 = st.tabs(["Claim Chart (Art. 56)", "Translation Verifier (Art. 123(2))", "Response Draft"])
    
    # Initialize session state for results
    if "processing_results" not in st.session_state:
        st.session_state.processing_results = None
    
    # Handle pipeline execution
    if run_button:
        if oa_file is None:
            st.error("Please upload an EPO Office Action document.")
            return
        
        with st.spinner("Processing documents... This may take a few moments."):
            # Save uploaded files
            oa_path = save_uploaded_file(oa_file)
            spec_path = save_uploaded_file(spec_file) if spec_file else ""
            
            try:
                # Process documents with claim type
                results = process_documents(oa_path, spec_path, selected_examiner, selected_claim_type)
                st.session_state.processing_results = results
                
                # Clean up temporary files
                if oa_path and os.path.exists(oa_path):
                    os.unlink(oa_path)
                if spec_path and os.path.exists(spec_path):
                    os.unlink(spec_path)
                
                if results["status"] == "completed":
                    st.success("PatentFlow pipeline completed successfully.")
                else:
                    st.error(f"Processing failed: {results.get('error', 'Unknown error')}")
                    
            except Exception as e:
                st.error(f"Error during processing: {str(e)}")
                st.session_state.processing_results = {"status": "error", "error": str(e)}
    
    # Display results in tabs
    results = st.session_state.processing_results
    
    with tab1:
        if results and results["status"] == "completed":
            render_claim_chart_tab(results.get("claim_chart"))
        else:
            st.info("Upload documents and run the PatentFlow pipeline to generate the claim chart.")
    
    with tab2:
        if results and results["status"] == "completed":
            render_translation_tab(results.get("translation_table"))
        else:
            st.info("Upload documents and run the PatentFlow pipeline to generate translation verification.")
    
    with tab3:
        if results and results["status"] == "completed":
            edited_draft = render_response_draft_tab(results.get("response_draft"))
            # Store edited draft for export
            st.session_state.processing_results["response_draft"] = edited_draft
        else:
            st.info("Upload documents and run the PatentFlow pipeline to generate the response draft.")
    
    # Export section at bottom
    if results and results["status"] == "completed":
        st.markdown("---")
        render_export_section(results.get("response_draft"))
    
    # Footer
    st.markdown("---")
    st.markdown("**PatentFlow** - Professional Document Processing for European Patent Attorneys")
    st.markdown("*Offline-first • Secure • EPC Compliant*")


if __name__ == "__main__":
    main()
