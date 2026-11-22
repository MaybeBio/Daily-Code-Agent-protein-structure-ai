
import streamlit as st
import streamlit.components.v1 as components
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import tempfile
import os
import io
import textwrap

from pathlib import Path
from collections import Counter
from Bio.PDB import PDBParser
from Bio.SeqUtils import seq1, molecular_weight
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
import py3Dmol


# =========================================================
# 1. PAGE CONFIGURATION
# =========================================================

st.set_page_config(
    page_title="AllergenAI | Protein Intelligence",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded"
)


# =========================================================
# 2. CUSTOM PROFESSIONAL THEME
# =========================================================

st.markdown("""
<style>

/* Main application background */
.stApp {
    background:
        radial-gradient(
            circle at 10% 5%,
            rgba(13, 148, 136, 0.16),
            transparent 28%
        ),
        radial-gradient(
            circle at 90% 90%,
            rgba(6, 182, 212, 0.10),
            transparent 30%
        ),
        linear-gradient(
            135deg,
            #071525 0%,
            #0b1d30 55%,
            #102a3b 100%
        );
    color: #e8f3f7;
}

header[data-testid="stHeader"] {
    background: rgba(7, 21, 37, 0.96);
}

header[data-testid="stHeader"] button {
    color: #e8f3f7;
}

/* Main content spacing */
.block-container {
    max-width: 1350px;
    padding-top: 2rem;
    padding-bottom: 3rem;
}

/* Headings */
h1, h2, h3 {
    color: #e9f8fa !important;
    font-weight: 700 !important;
}

/* Body text */
p, label {
    color: #c4d9e2;
}

/* Sidebar */
section[data-testid="stSidebar"] {
    background: linear-gradient(
        180deg,
        #061321 0%,
        #102b40 100%
    );
    border-right: 1px solid #1d5263;
}

/* Sidebar title */
section[data-testid="stSidebar"] h1 {
    color: #5eead4 !important;
}

/* Sidebar navigation text */
section[data-testid="stSidebar"] label {
    color: #d5edf0 !important;
}

/* Buttons */
.stButton > button {
    background: linear-gradient(
        90deg,
        #0d9488,
        #0891b2
    );
    color: white !important;
    border: none;
    border-radius: 12px;
    padding: 0.65rem 1.2rem;
    font-weight: 700;
    transition: 0.2s;
}

.stButton > button:hover {
    background: linear-gradient(
        90deg,
        #14b8a6,
        #22d3ee
    );
    transform: translateY(-2px);
    border: none;
}

/* Metric cards */
div[data-testid="stMetric"] {
    background: rgba(20, 53, 72, 0.82);
    border: 1px solid rgba(45, 212, 191, 0.30);
    padding: 18px;
    border-radius: 16px;
}

/* Metric values */
div[data-testid="stMetricValue"] {
    color: #5eead4;
    font-weight: 800;
}

/* File uploader */
div[data-testid="stFileUploader"] {
    background: rgba(17, 48, 67, 0.65);
    border: 1px dashed #2dd4bf;
    padding: 14px;
    border-radius: 14px;
}

/* Dataframe */
div[data-testid="stDataFrame"] {
    border: 1px solid #245466;
    border-radius: 12px;
}

/* Progress bar */
div[data-testid="stProgressBar"] > div > div {
    background: linear-gradient(
        90deg,
        #0d9488,
        #22d3ee
    );
}

/* Alerts */
div[data-testid="stAlert"] {
    border-radius: 12px;
}

/* Dividers */
hr {
    border-color: rgba(45, 212, 191, 0.25);
}

/* Captions */
.stCaption {
    color: #8baebb !important;
}

/* Input fields */
.stTextInput input,
.stTextArea textarea {
    background-color: #102b40;
    color: #e8f3f7;
    border: 1px solid #245466;
    border-radius: 10px;
}

/* Footer */
footer {
    visibility: hidden;
}

</style>
""", unsafe_allow_html=True)


def render_html(markup, container=st):
    markup = textwrap.dedent(markup)
    markup = "\n".join(line.lstrip() for line in markup.splitlines())
    container.markdown(markup, unsafe_allow_html=True)


# =========================================================
# 3. PROJECT PATHS
# =========================================================

APP_FOLDER = Path(__file__).parent

MODEL_PATH = APP_FOLDER / "allergen3d_cnn_final.pt"

METRICS_PATH = APP_FOLDER / "3d_cnn_evaluation_metrics.csv"


# =========================================================
# 4. MODEL SETTINGS
# =========================================================

GRID_SIZE = 48
VOXEL_SIZE = 2.5

ELEMENTS = ["C", "N", "O", "S", "P"]

device = torch.device(
    "cuda" if torch.cuda.is_available() else "cpu"
)


# =========================================================
# 5. DEFINE EXISTING 3D CNN
# =========================================================

class Allergen3DCNN(nn.Module):

    def __init__(self):

        super(Allergen3DCNN, self).__init__()

        self.features = nn.Sequential(

            nn.Conv3d(5, 16, kernel_size=3, padding=1),
            nn.BatchNorm3d(16),
            nn.ReLU(),
            nn.MaxPool3d(2),

            nn.Conv3d(16, 32, kernel_size=3, padding=1),
            nn.BatchNorm3d(32),
            nn.ReLU(),
            nn.MaxPool3d(2),

            nn.Conv3d(32, 64, kernel_size=3, padding=1),
            nn.BatchNorm3d(64),
            nn.ReLU(),
            nn.MaxPool3d(2),

            nn.AdaptiveAvgPool3d(1)
        )

        self.classifier = nn.Sequential(

            nn.Flatten(),
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(32, 1)
        )

    def forward(self, x):

        x = self.features(x)
        x = self.classifier(x)

        return x


# =========================================================
# 6. LOAD TRAINED MODEL
# =========================================================

@st.cache_resource
def load_model():

    if not MODEL_PATH.exists():

        raise FileNotFoundError(
            f"Model file not found: {MODEL_PATH}"
        )

    model = Allergen3DCNN().to(device)

    checkpoint = torch.load(
        MODEL_PATH,
        map_location=device,
        weights_only=True
    )

    model.load_state_dict(checkpoint)

    model.eval()

    return model


# =========================================================
# 7. PDB TO VOXEL CONVERSION
# =========================================================

def pdb_to_voxel(pdb_file):

    parser = PDBParser(QUIET=True)

    structure = parser.get_structure(
        "protein",
        pdb_file
    )

    coordinates = []
    elements = []

    for atom in structure.get_atoms():

        element = atom.element.upper()

        if element in ELEMENTS:

            coordinates.append(atom.coord)
            elements.append(element)

    if len(coordinates) == 0:

        raise ValueError(
            "No supported atoms found in PDB file."
        )

    coordinates = np.array(
        coordinates,
        dtype=np.float32
    )

    center = coordinates.mean(axis=0)

    coordinates = coordinates - center

    voxel = np.zeros(
        (
            5,
            GRID_SIZE,
            GRID_SIZE,
            GRID_SIZE
        ),
        dtype=np.float32
    )

    center_grid = GRID_SIZE // 2

    outside_atoms = 0

    for coord, element in zip(
        coordinates,
        elements
    ):

        index = np.round(
            coord / VOXEL_SIZE + center_grid
        ).astype(int)

        x, y, z = index

        if (
            0 <= x < GRID_SIZE
            and 0 <= y < GRID_SIZE
            and 0 <= z < GRID_SIZE
        ):

            channel = ELEMENTS.index(element)

            voxel[channel, x, y, z] = 1.0

        else:

            outside_atoms += 1

    return voxel, outside_atoms, len(coordinates)


# =========================================================
# 8. PREDICTION FUNCTION
# =========================================================

def predict_protein(pdb_file):

    voxel, outside_atoms, total_atoms = pdb_to_voxel(
        pdb_file
    )

    input_tensor = torch.tensor(
        voxel,
        dtype=torch.float32
    ).unsqueeze(0).to(device)

    model = load_model()

    with torch.no_grad():

        output = model(input_tensor)

        probability = torch.sigmoid(output).item()

    prediction = (
        "Allergen"
        if probability >= 0.5
        else "Non-Allergen"
    )

    return (
        prediction,
        probability,
        outside_atoms,
        total_atoms
    )


# =========================================================
# 9. EXTRACT PROTEIN INFORMATION
# =========================================================

def get_protein_information(pdb_file):

    parser = PDBParser(QUIET=True)

    structure = parser.get_structure(
        "protein",
        pdb_file
    )

    first_model = structure[0]

    sequences = {}

    residue_count = 0
    atom_count = 0

    element_counts = Counter()

    for chain in first_model:

        sequence = ""

        for residue in chain:

            if residue.id[0] == " ":

                residue_count += 1

                amino_acid = seq1(
                    residue.resname,
                    custom_map={"UNK": "X"}
                )

                sequence += amino_acid

        sequences[chain.id] = sequence

    for atom in structure.get_atoms():

        atom_count += 1

        element = atom.element.upper()

        if element:

            element_counts[element] += 1

    combined_sequence = "".join(
        sequences.values()
    )

    weight = None

    try:

        if combined_sequence and "X" not in combined_sequence:

            weight = molecular_weight(
                combined_sequence,
                seq_type="protein"
            )

    except Exception:

        weight = None

    amino_acid_counts = Counter(
        combined_sequence
    )

    return {

        "sequences": sequences,
        "sequence": combined_sequence,
        "residues": residue_count,
        "atoms": atom_count,
        "chains": list(sequences.keys()),
        "elements": dict(element_counts),
        "amino_acids": dict(amino_acid_counts),
        "molecular_weight": weight

    }


# =========================================================
# 10. INTERACTIVE 3D PROTEIN VIEWER
# =========================================================

def show_3d_structure(pdb_text, style="Cartoon"):

    view = py3Dmol.view(
        width=1100,
        height=600
    )

    view.addModel(
        pdb_text,
        "pdb"
    )

    if style == "Cartoon":

        view.setStyle({
            "cartoon": {
                "color": "spectrum"
            }
        })

    elif style == "Stick":

        view.setStyle({
            "stick": {
                "radius": 0.15
            }
        })

    elif style == "Sphere":

        view.setStyle({
            "sphere": {
                "scale": 0.3
            }
        })

    elif style == "Surface":

        view.setStyle({
            "cartoon": {
                "color": "spectrum"
            }
        })

        view.addSurface(
            py3Dmol.VDW,
            {
                "opacity": 0.65,
                "color": "lightblue"
            }
        )

    view.zoomTo()

    components.html(
        view._make_html(),
        height=620,
        scrolling=False
    )


# =========================================================
# 11. CREATE PDF REPORT
# =========================================================

def create_pdf(
    filename,
    prediction,
    probability,
    info,
    outside,
    total
):

    buffer = io.BytesIO()

    pdf = canvas.Canvas(
        buffer,
        pagesize=A4
    )

    width, height = A4

    y = height - 55

    pdf.setFillColorRGB(
        0.04, 0.18, 0.27
    )

    pdf.rect(
        0,
        height - 100,
        width,
        100,
        fill=1,
        stroke=0
    )

    pdf.setFillColorRGB(
        1, 1, 1
    )

    pdf.setFont(
        "Helvetica-Bold",
        22
    )

    pdf.drawString(
        45,
        height - 55,
        "AllergenAI Protein Report"
    )

    y = height - 130

    pdf.setFillColorRGB(
        0.05, 0.15, 0.23
    )

    pdf.setFont(
        "Helvetica-Bold",
        14
    )

    pdf.drawString(
        45,
        y,
        "Prediction Results"
    )

    y -= 30

    pdf.setFont(
        "Helvetica",
        11
    )

    details = [

        f"Protein file: {filename}",

        f"Prediction: {prediction}",

        f"Allergen probability: {probability * 100:.2f}%",

        f"Non-allergen probability: {(1-probability)*100:.2f}%"

    ]

    for detail in details:

        pdf.drawString(
            50,
            y,
            detail
        )

        y -= 23

    y -= 15

    pdf.setFont(
        "Helvetica-Bold",
        14
    )

    pdf.drawString(
        45,
        y,
        "Protein Information"
    )

    y -= 30

    pdf.setFont(
        "Helvetica",
        11
    )

    details = [

        f"Number of residues: {info['residues']}",

        f"Number of atoms: {info['atoms']}",

        f"Protein chains: {', '.join(info['chains'])}",

        f"Supported atoms: {total}",

        f"Atoms outside voxel grid: {outside}"

    ]

    if info["molecular_weight"] is not None:

        details.append(
            f"Molecular weight: {info['molecular_weight']:.2f} Da"
        )

    for detail in details:

        pdf.drawString(
            50,
            y,
            detail
        )

        y -= 22

    y -= 15

    pdf.setFont(
        "Helvetica-Bold",
        14
    )

    pdf.drawString(
        45,
        y,
        "Atom Composition"
    )

    y -= 25

    pdf.setFont(
        "Helvetica",
        10
    )

    for element, count in info["elements"].items():

        if y < 90:

            pdf.showPage()
            y = height - 60

            pdf.setFont(
                "Helvetica",
                10
            )

        pdf.drawString(
            50,
            y,
            f"{element}: {count}"
        )

        y -= 18

    y -= 25

    pdf.setFont(
        "Helvetica",
        9
    )

    pdf.drawString(
        45,
        y,
        "Research prototype. Not a clinical diagnosis."
    )

    pdf.save()

    buffer.seek(0)

    return buffer


# =========================================================
# 12. HEADER FUNCTION
# =========================================================

def show_header(title, subtitle):

    render_html(f"""
        <div style="
            padding: 26px;
            border-radius: 20px;
            background: linear-gradient(
                110deg,
                #10334a,
                #075e65
            );
            border: 1px solid #2dd4bf;
            margin-bottom: 25px;
            box-shadow: 0 8px 30px rgba(0,0,0,0.18);
        ">

            <h1 style="
                color: #ffffff;
                font-size: 36px;
                margin-bottom: 8px;
            ">
                🧬 {title}
            </h1>

            <p style="
                color: #c5f7f0;
                font-size: 16px;
                margin: 0;
            ">
                {subtitle}
            </p>

        </div>
        """)


# =========================================================
# 13. SIDEBAR NAVIGATION
# =========================================================

render_html("""
    <div style="
        padding: 18px;
        border-radius: 15px;
        background: linear-gradient(
            135deg,
            #10334a,
            #075e65
        );
        border: 1px solid #2dd4bf;
        margin-bottom: 20px;
    ">
        <h1 style="
            color: #5eead4;
            font-size: 27px;
            margin: 0;
        ">
            🧬 AllergenAI
        </h1>

        <p style="
            color: #c5f7f0;
            font-size: 12px;
            margin: 5px 0 0 0;
        ">
            Protein Structure Intelligence
        </p>
    </div>
    """, container=st.sidebar)

page = st.sidebar.radio(
    "NAVIGATION",
    [
        "Home",
        "Protein Prediction",
        "3D Structure Viewer",
        "Protein Analysis",
        "Model Performance",
        "About Project"
    ]
)

st.sidebar.divider()

st.sidebar.markdown(
    "**Model Information**"
)

st.sidebar.caption("Architecture: 3D CNN")

st.sidebar.caption("Input: PDB Structure")

st.sidebar.caption("Grid: 48 × 48 × 48")

st.sidebar.caption(f"Device: {device}")


# =========================================================
# 14. HOME PAGE
# =========================================================

if page == "Home":

    show_header(
        "AllergenAI",
        "AI-Powered Protein Structure Analysis and Allergen Prediction"
    )

    st.markdown(
        """
        AllergenAI is an experimental BioAI application
        designed to explore protein allergen classification
        using three-dimensional structural information.
        """
    )

    st.divider()

    col1, col2, col3 = st.columns(3)

    col1.metric(
        "Deep Learning Model",
        "3D CNN"
    )

    col2.metric(
        "Input Structure",
        "PDB"
    )

    col3.metric(
        "Classification",
        "Binary"
    )

    st.divider()

    st.subheader("Explore AllergenAI")

    col1, col2 = st.columns(2)

    with col1:

        render_html("""
            <div style="
                background: rgba(20,53,72,0.8);
                border: 1px solid #2dd4bf;
                border-radius: 16px;
                padding: 22px;
                min-height: 165px;
            ">
                <h3>🔬 Protein Prediction</h3>
                <p>Upload a protein PDB structure and
                obtain an experimental allergen prediction.</p>
            </div>
            """)

        st.write("")

        render_html("""
            <div style="
                background: rgba(20,53,72,0.8);
                border: 1px solid #2dd4bf;
                border-radius: 16px;
                padding: 22px;
                min-height: 165px;
            ">
                <h3>📊 Protein Analysis</h3>
                <p>Explore protein sequences, amino acid
                composition, molecular weight and atom counts.</p>
            </div>
            """)

    with col2:

        render_html("""
            <div style="
                background: rgba(20,53,72,0.8);
                border: 1px solid #2dd4bf;
                border-radius: 16px;
                padding: 22px;
                min-height: 165px;
            ">
                <h3>🧬 3D Structure Viewer</h3>
                <p>Rotate, zoom and explore uploaded protein
                structures interactively.</p>
            </div>
            """)

        st.write("")

        render_html("""
            <div style="
                background: rgba(20,53,72,0.8);
                border: 1px solid #2dd4bf;
                border-radius: 16px;
                padding: 22px;
                min-height: 165px;
            ">
                <h3>📈 Model Performance</h3>
                <p>Review the available evaluation metrics
                from the trained 3D CNN.</p>
            </div>
            """)

    st.divider()

    st.info(
        "Upload a PDB file in Protein Prediction to begin."
    )


# =========================================================
# 15. PROTEIN PREDICTION PAGE
# =========================================================

elif page == "Protein Prediction":

    show_header(
        "Protein Prediction",
        "Upload a PDB file to analyse its structure and predict allergen classification"
    )

    uploaded_file = st.file_uploader(
        "Upload Protein PDB File",
        type=["pdb"],
        key="prediction_upload"
    )

    if uploaded_file is not None:

        pdb_bytes = uploaded_file.getvalue()

        st.success(
            f"Uploaded successfully: {uploaded_file.name}"
        )

        st.caption(
            f"File size: {len(pdb_bytes) / 1024:.2f} KB"
        )

        if st.button(
            "🔬 Predict Allergenicity",
            type="primary"
        ):

            temp_path = None

            try:

                with st.spinner(
                    "Loading model and analysing protein structure..."
                ):

                    with tempfile.NamedTemporaryFile(
                        suffix=".pdb",
                        delete=False
                    ) as temp_file:

                        temp_file.write(pdb_bytes)

                        temp_path = temp_file.name

                    prediction, probability, outside, total = (
                        predict_protein(temp_path)
                    )

                    info = get_protein_information(
                        temp_path
                    )

                st.session_state["prediction_result"] = {

                    "filename": uploaded_file.name,

                    "prediction": prediction,

                    "probability": probability,

                    "outside": outside,

                    "total": total,

                    "info": info,

                    "pdb_text": pdb_bytes.decode(
                        "utf-8",
                        errors="replace"
                    )

                }

            except Exception as e:

                st.error(
                    f"Prediction failed: {str(e)}"
                )

            finally:

                if (
                    temp_path is not None
                    and os.path.exists(temp_path)
                ):

                    os.remove(temp_path)

        result = st.session_state.get(
            "prediction_result"
        )

        if (
            result is not None
            and result["filename"] == uploaded_file.name
        ):

            st.divider()

            st.subheader("Prediction Results")

            prediction = result["prediction"]

            probability = result["probability"]

            if prediction == "Allergen":

                st.error(
                    "PREDICTION: ALLERGEN"
                )

            else:

                st.success(
                    "PREDICTION: NON-ALLERGEN"
                )

            col1, col2 = st.columns(2)

            col1.metric(
                "Allergen Probability",
                f"{probability * 100:.2f}%"
            )

            col2.metric(
                "Non-Allergen Probability",
                f"{(1-probability)*100:.2f}%"
            )

            st.write("Allergen probability")

            st.progress(
                float(probability)
            )

            st.divider()

            st.subheader("Protein Structure Information")

            col1, col2, col3 = st.columns(3)

            col1.metric(
                "Amino Acid Residues",
                result["info"]["residues"]
            )

            col2.metric(
                "Supported Atoms",
                result["total"]
            )

            col3.metric(
                "Atoms Outside Grid",
                result["outside"]
            )

            if result["outside"] > 0:

                st.warning(
                    "Some atoms were outside the voxel grid. "
                    "Interpret this prediction cautiously."
                )

            st.divider()

            st.subheader("Protein 3D Preview")

            show_3d_structure(
                result["pdb_text"],
                "Cartoon"
            )

            st.divider()

            st.subheader("Download Your Analysis Report")

            pdf = create_pdf(
                result["filename"],
                prediction,
                probability,
                result["info"],
                result["outside"],
                result["total"]
            )

            st.download_button(
                label="📄 Download PDF Report",
                data=pdf,
                file_name="AllergenAI_Protein_Report.pdf",
                mime="application/pdf"
            )

            st.warning(
                "This is an experimental research prediction, "
                "not a clinical diagnosis or confirmation of "
                "allergenicity. Model probabilities are not "
                "necessarily calibrated clinical risks."
            )


# =========================================================
# 16. 3D STRUCTURE VIEWER PAGE
# =========================================================

elif page == "3D Structure Viewer":

    show_header(
        "3D Protein Structure Viewer",
        "Explore protein structures in an interactive molecular viewer"
    )

    uploaded_file = st.file_uploader(
        "Upload a PDB structure",
        type=["pdb"],
        key="viewer_upload"
    )

    if uploaded_file is not None:

        pdb_text = uploaded_file.getvalue().decode(
            "utf-8",
            errors="replace"
        )

        st.success(
            f"Structure loaded: {uploaded_file.name}"
        )

        style = st.selectbox(
            "Choose molecular representation",
            [
                "Cartoon",
                "Stick",
                "Sphere",
                "Surface"
            ]
        )

        st.subheader("Interactive Protein Structure")

        try:

            show_3d_structure(
                pdb_text,
                style
            )

            st.caption(
                "Drag to rotate, scroll to zoom and "
                "use the viewer controls to explore the molecule."
            )

        except Exception as e:

            st.error(
                f"3D viewer error: {str(e)}"
            )


# =========================================================
# 17. PROTEIN ANALYSIS PAGE
# =========================================================

elif page == "Protein Analysis":

    show_header(
        "Protein Analysis",
        "Explore amino acid sequences and structural composition"
    )

    uploaded_file = st.file_uploader(
        "Upload a PDB file",
        type=["pdb"],
        key="analysis_upload"
    )

    if uploaded_file is not None:

        temp_path = None

        try:

            with tempfile.NamedTemporaryFile(
                suffix=".pdb",
                delete=False
            ) as temp_file:

                temp_file.write(
                    uploaded_file.getvalue()
                )

                temp_path = temp_file.name

            info = get_protein_information(
                temp_path
            )

            st.subheader("General Protein Information")

            col1, col2, col3 = st.columns(3)

            col1.metric(
                "Residues",
                info["residues"]
            )

            col2.metric(
                "Total Atoms",
                info["atoms"]
            )

            col3.metric(
                "Number of Chains",
                len(info["chains"])
            )

            if info["molecular_weight"] is not None:

                st.metric(
                    "Molecular Weight",
                    f"{info['molecular_weight']:,.2f} Da"
                )

            st.divider()

            st.subheader("Amino Acid Sequence")

            st.text_area(
                "Extracted protein sequence",
                value=info["sequence"],
                height=180
            )

            st.write(
                "Sequence length:",
                len(info["sequence"])
            )

            st.divider()

            st.subheader("Amino Acid Composition")

            amino_df = pd.DataFrame(
                list(info["amino_acids"].items()),
                columns=[
                    "Amino Acid",
                    "Count"
                ]
            )

            if not amino_df.empty:

                st.bar_chart(
                    amino_df.set_index("Amino Acid")
                )

                st.dataframe(
                    amino_df,
                    use_container_width=True
                )

            st.divider()

            st.subheader("Atom Composition")

            atom_df = pd.DataFrame(
                list(info["elements"].items()),
                columns=[
                    "Element",
                    "Atom Count"
                ]
            )

            st.bar_chart(
                atom_df.set_index("Element")
            )

            st.dataframe(
                atom_df,
                use_container_width=True
            )

            st.write(
                "Protein chains:",
                ", ".join(info["chains"])
            )

        except Exception as e:

            st.error(
                f"Protein analysis failed: {str(e)}"
            )

        finally:

            if (
                temp_path is not None
                and os.path.exists(temp_path)
            ):

                os.remove(temp_path)


# =========================================================
# 18. MODEL PERFORMANCE PAGE
# =========================================================

elif page == "Model Performance":

    show_header(
        "Model Performance",
        "Review the evaluation results of the trained 3D CNN"
    )

    if METRICS_PATH.exists():

        metrics = pd.read_csv(
            METRICS_PATH
        )

        st.subheader("Evaluation Metrics")

        st.dataframe(
            metrics,
            use_container_width=True
        )

        numeric_columns = metrics.select_dtypes(
            include=np.number
        ).columns.tolist()

        if numeric_columns:

            st.divider()

            st.subheader("Metric Visualization")

            st.bar_chart(
                metrics[numeric_columns]
            )

        else:

            st.info(
                "The metrics file does not contain numeric columns."
            )

    else:

        st.warning(
            "Evaluation metrics file not found."
        )

    st.caption(
        "Only metrics available in the supplied evaluation file "
        "are displayed. No missing performance values are assumed."
    )


# =========================================================
# 19. ABOUT PROJECT PAGE
# =========================================================

elif page == "About Project":

    show_header(
        "About AllergenAI",
        "A research prototype for protein allergen classification using deep learning"
    )

    st.subheader("Project Objective")

    st.write(
        """
        The objective of AllergenAI is to explore the use
        of three-dimensional protein structural information
        for allergen and non-allergen classification.
        """
    )

    st.divider()

    st.subheader("Model Architecture")

    st.markdown(
        """
        - 3D Convolutional Neural Network
        - Three convolutional blocks
        - Batch normalization
        - ReLU activation
        - Max pooling
        - Adaptive average pooling
        - Fully connected classification layers
        """
    )

    st.divider()

    st.subheader("Input Representation")

    col1, col2 = st.columns(2)

    col1.metric(
        "Voxel Grid",
        "48 × 48 × 48"
    )

    col2.metric(
        "Voxel Size",
        "2.5 Å"
    )

    st.write(
        "Atom channels: Carbon, Nitrogen, Oxygen, Sulfur and Phosphorus."
    )

    st.divider()

    st.subheader("Model Output")

    st.write(
        """
        The current model performs binary classification:

        - Allergen
        - Non-Allergen
        """
    )

    st.divider()

    st.subheader("Future Development")

    st.markdown(
        """
        - Allergen source classification
        - Allergen protein family classification
        - Improved structural feature analysis
        - Model interpretability
        - Larger and more diverse structural datasets
        """
    )

    st.warning(
        "AllergenAI is an experimental research prototype. "
        "Its predictions require independent experimental "
        "validation and should not be used for clinical or "
        "food-safety decisions."
    )


# =========================================================
# 20. FOOTER
# =========================================================

render_html("""
    <hr>

    <div style="
        text-align: center;
        padding: 15px;
        color: #8baebb;
        font-size: 12px;
    ">
        🧬 AllergenAI | AI-Based Protein Structure Analysis
        <br>
        Experimental BioAI Research Application
    </div>
    """)
