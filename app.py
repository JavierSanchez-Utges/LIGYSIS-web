### PACKAGE IMPORTS ###

import os
import re
import io
import csv
import pickle
import zipfile
import numpy as np
import pandas as pd

from flask import Flask, render_template, url_for, request, redirect, jsonify, Response, send_file

from config import BASE_DIR, DATA_FOLDER, SITE_TABLES_FOLDER, RES_TABLES_FOLDER, REP_STRUCS_FOLDER, BS_RESS_FOLDER, MAPPINGS_FOLDER, STATS_FOLDER, ENTRY_NAMES_FOLDER

### FUNCTIONS ###

def load_pickle(f_in): # loads pickle and returns data
    """
    Loads data from pickle.
    """
    with open(f_in, "rb") as f:
        data = pickle.load(f)
    return data

def convert_numpy(obj): # utility function to ensure object types are correct
    if isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, dict):
        return {k: convert_numpy(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [convert_numpy(v) for v in obj]
    return obj

def extract_open_files(cxc_in): # extracts dictionary of order of opened files from ChimeraX .cxc
    """
    reads ChimeraX command file (.cxc) generated by
    LIGYSIS and extracts all the models opened and the
    order they are in. Returns a dictionary.
    """
    open_files_dict = {}
    file_counter = 1
    with open(cxc_in, 'r') as file:
        for line in file:
            if line.startswith("open"):
                file_name = line.strip().split()[1]
                if file_name.endswith(".cif"):
                    open_files_dict[file_counter] = file_name
                    file_counter += 1
    return open_files_dict
    
def transform_lines2(defattr_in, opened_chimX, loaded_3dmol): # gets binding site ID attribute data from .attr, .cxc and 3DMol.js
    """
    reads ChimeraX attribute file (.defattr) and uses ordered loaded
    models dictionary to return PyMol property setting commands as well
    as the unique binding site IDs.
    """
    bs_ids = []
    data = []
    with open(defattr_in, 'r') as file:
        for line in file:
            match = re.match(r'\s+#(\d+)/(\w+):(\d+)\s+(-?\d+)', line) # finding regex match on .attr file
            if match:
                key, chain, resi, p_bs = match.groups() # extracts binding site information
                #print(key, chain, resi, p_bs)
                bs_ids.append(p_bs) # adds binding site ID to list
                # print(opened_chimX[int(key)], loaded_3dmol)
                if opened_chimX[int(key)] in loaded_3dmol:
                    mod_id = loaded_3dmol[opened_chimX[int(key)]]
                    data.append((mod_id, chain, int(resi), int(p_bs))) # adds mapping data tuple to list
                else:
                    print("Model not found")
    bs_ids = sorted(int(item) for item in set(bs_ids)) # gets unique set of sorted binding site IDs
    return data, bs_ids

def transform_dict(input_dict):
    """
    Transforms a dictionary where keys are in the format 'prefix_ATP_D_400'
    into a list of tuples in the format [("ATP", "D", 400, value),]

    Args:
    input_dict (dict): Dictionary to be transformed.

    Returns:
    list: A list of tuples containing transformed data.
    """
    result_list = []
    for key, value in input_dict.items():
        # Split the key by '_' and extract necessary parts
        parts = key.split('_')
        # Append the new tuple to the result list
        result_list.append((parts[1], parts[2], int(parts[3]), value))
    return result_list

def convert_mapping_dict(d):
    rfd = {}
    for k1, v1 in d.items():
        rfd[k1] = {}
        for k2, v2 in v1.items():
            rfd[k1][k2] = {}
            for k3, v3 in v2.items():
                rfd[k1][k2][int(k3)] = int(v3)
                # for k4, v4 in v3.items():
                #     rfd[k1][k2][k3][int(k4)] = int(v4)
    return rfd

def generate_pseudobond_lines(df):
    # Create an empty list to store the formatted strings
    output = []
    
    # Group the DataFrame by the 'width' column
    grouped = df.groupby('width')
    
    # Iterate over each group (by width)
    for width, group in grouped:
        # Add the radius line
        output.append(f"; radius = {width}")
        
        # Iterate over each row in the group
        for _, row in group.iterrows():
            # Extract necessary information for the format
            end_part = f"/{row['auth_asym_id_end']}:{row['auth_seq_id_end']}@{row['auth_atom_id_end']}"
            begin_part = f"/{row['auth_asym_id_bgn']}:{row['auth_seq_id_bgn']}@{row['auth_atom_id_bgn']}"
            
            # Combine end, begin parts, and add the color
            formatted_string = f"{end_part} {begin_part} {row['color']}"
            
            # Append the formatted string to the output list
            output.append(formatted_string)
    
    return output

### SOME FIXED VARIABLES ###

colors = load_pickle(os.path.join(DATA_FOLDER, "sample_colors_hex.pkl")) # sample colors

headings = ["ID", "RSA", "DS", "MES", "Size", "Cluster", "FS"] # headings of binding site table

cc_new = ["UPResNum", "MSACol", "DS", "MES", "p", "AA", "RSA", "SS"] # headings of binding residue table

bs_table_tooltips = [ # hover tooltips for binding site table
    "This is the ligand binding site identifier",
    "This is the site's avg. RSA",
    "This is the site's avg. divergence score",
    "This is the site's avg. missense enrichment score",
    "This is the site's size (in aa)",
    "This is the site's RSA cluster label",
    "This is the site's functional score",
]

bs_ress_table_tooltips = [ # hover tooltips for binding residue table
    "This is the residue's UniProt number",
    "This is the residue's alignment column",
    "This is the residue's divergence score",
    "This is the residue's missense enrichment score",
    "This is the MES p-value",
    "This is the residue's amino acid",
    "This is the residue's RSA",
    "This is the residue's secondary structure",
]


arpeggio_cols = [
    'contact', 'distance',
    'auth_asym_id_end', 'auth_atom_id_end', 'auth_seq_id_end',
    'label_comp_id_end', 'auth_asym_id_bgn',
    'auth_atom_id_bgn', 'auth_seq_id_bgn', 'label_comp_id_bgn',
    'orig_label_asym_id_end', 'UniProt_ResNum_end',
    'coords_end', 'coords_bgn', 'width', 'color'
]

extra_cxc_lines = [
    "color white; set bgColor white;",
    "set silhouette ON; set silhouetteWidth 2; set silhouetteColor black;",
    "~disp; select ~protein; ~select : HOH; ~select ::binding_site==-1; disp sel; ~sel;",
    "col :HOH orange; col ::binding_site==-1 grey;",
    "surf protein; transparency 30 s;",
]

### INTERACTIONS README ###
contacts_info = """
Arpeggio protein-ligand contacts visualisation

The Arpeggio colour scheme is used to visually represent different types of interactions. Below are the hex codes, their corresponding color names and the interactions they represent.

- #000000: Black - Represents 'clash' interactions.
- #999999: Dim Gray - Used for 'covalent', 'vdw_clash', 'vdw', and 'proximal' interactions.
- #f04646: Red Orange - Used for 'hbond' and 'polar' interactions.
- #fc7600: Pumpkin - Represents 'weak_hbond' and 'weak_polar' interactions.
- #3977db: Royal Blue - Indicates 'xbond' (halogen bond) interactions.
- #e3e159: Pale Goldenrod - Represents 'ionic' interactions.
- #800080: Purple - Used for 'metal_complex' interactions.
- #00ccff: Vivid Sky Blue - Indicates 'aromatic' interactions.
- #006633: Dark Green - Represents 'hydrophobic' interactions.
- #ff007f: Bright Pink - Used for 'carbonyl' interactions.

The width of the pseudobonds represents the distance between the interacting atoms. Width of 0.125 if the atoms are within VdW Clash distance, otherwise 0.0625.
"""

### READING INPUT DATA ###

prot_ids = load_pickle(os.path.join(DATA_FOLDER, "biolip_up_ids_15000_accs.pkl")) # protein idshon

#### FLASK APP ###

app = Flask(__name__)
    
@app.route('/', methods=['POST', 'GET'])
def index(): # route for index main site
    if request.method == 'POST':

        prot_id = request.form['proteinId']

        if prot_id in prot_ids:

            prot_seg_rep_strucs = load_pickle(os.path.join(REP_STRUCS_FOLDER, "{}_segs_rep_strucs.pkl".format(prot_id))) # representative structures dict (only successfully run segments)

            first_seg = sorted(list(prot_seg_rep_strucs[prot_id].keys()))[0]

            return redirect(url_for('results', prot_id = prot_id, seg_id = first_seg)) # renders results page
        else:
            return render_template('error.html', prot_id = prot_id)

    else:
        return render_template('index.html', prot_ids = prot_ids) # renders home page with all tasks

@app.route('/results/<prot_id>/<seg_id>', methods = ['POST', 'GET'])
def results(prot_id, seg_id): # route for results site. Takes Prot ID and Seg ID

    seg_name = prot_id + "_" + seg_id # combining UniProt ID and Segment ID into SEGMENT NAME

    bss_data = pd.read_pickle(os.path.join(SITE_TABLES_FOLDER, "{}_bss.pkl".format(prot_id))) # site data
    bss_data = bss_data.fillna("NaN") # pre-processing could also be done before saving the pickle
    bss_data.columns = headings # changing table column names

    bss_prot = bss_data[bss_data.ID.str.contains(seg_name)].copy() # extracting Segment of interest rows from table

    bss_prot.ID = bss_prot.ID.str.split("_").str[2] # extracting binding site ID from binding site name, which is UniProt ID _ Segment ID _ Binding Site ID

    bss_prot.ID = bss_prot.ID.astype(int) # changing binding site ID to integer data type

    bss_prot = bss_prot.sort_values(by = "ID") # sorting binding site table rows by ID

    first_site = bss_prot.ID.unique().tolist()[0] # first binding site ID

    first_site_name = seg_name + "_" + str(first_site) # name of first binding site (data shown by default when oppening page)

    bss_ress = pd.read_pickle(os.path.join(RES_TABLES_FOLDER, "{}_ress.pkl".format(seg_name))) # residue data
    bss_ress = bss_ress.fillna("NaN") # pre-processing could also be done before saving the pickle

    first_site_data = bss_ress.query('bs_id == @first_site_name')[cc_new].to_dict(orient="list") # data of first binding site residues

    data1 = bss_prot.to_dict(orient="list") # converting table to dictionary to pass to client

    prot_ress = bss_ress.query('up_acc == @prot_id')[cc_new]

    prot_seg_rep_strucs = load_pickle(os.path.join(REP_STRUCS_FOLDER, "{}_segs_rep_strucs.pkl".format(prot_id))) # representative structures dict (only successfully run segments)

    segment_reps = prot_seg_rep_strucs[prot_id]

    data2 = prot_ress.to_dict(orient="list")

    bs_ress_dict = load_pickle(os.path.join(DATA_FOLDER, "example", "other", f'{prot_id}_{seg_id}_ALL_inf_bss_ress.pkl'))

    seg_ress_dict = bs_ress_dict#[prot_id][seg_id]
    seg_ress_dict = {str(key): value for key, value in seg_ress_dict.items()}
    
    seg_ress_dict["ALL_BINDING"] = sorted(list(set([el2 for el in seg_ress_dict.values() for el2 in el]))) # add key: "ALL_BINDING" and value a sorted set of all binding residues
    
    protein_atoms_dict = load_pickle(os.path.join(DATA_FOLDER, "segment_prot_struc_dict_DEF.pkl"))

    prot_atoms_rep = list(protein_atoms_dict[prot_id][seg_id].keys())[0]

    prot_pdb_id, prot_pdb_chain = prot_atoms_rep.split("_")

    pdb2up_dict = load_pickle(f'{DATA_FOLDER}/{prot_id}/{seg_id}/mapping/{prot_pdb_id}_pdb2up.pkl')
    up2pdb_dict = load_pickle(f'{DATA_FOLDER}/{prot_id}/{seg_id}/mapping/{prot_pdb_id}_up2pdb.pkl')

    seg_stats = load_pickle(os.path.join(STATS_FOLDER, "{}_stats.pkl".format(seg_name)))

    entry_name = load_pickle(os.path.join(ENTRY_NAMES_FOLDER, "{}_name.pkl".format(prot_id)))[prot_id]
    
    seg_stats_converted = convert_numpy(seg_stats) # converting data type of Segment summary statistics

    up2pdb_dict_converted = {k: {k2:{int(k3):int(v3) for k3, v3 in v2.items()} for k2, v2 in v.items()} for k, v in up2pdb_dict.items()}

    pdb2up_dict_converted = {k: {k2:{int(k3):int(v3) for k3, v3 in v2.items()} for k2, v2 in v.items()} for k, v in pdb2up_dict.items()}

    assembly_pdbs = os.listdir(os.path.join(DATA_FOLDER, prot_id, str(seg_id), "assemblies")) # CIF bio assembly file names
    assembly_pdbs = [el for el in assembly_pdbs if el.endswith(".cif")]

    assembly_pdb_ids = sorted(list(set([el.split("_")[0] for el in assembly_pdbs])),) # sorted unique PDB IDs

    simple_pdbs = os.listdir(os.path.join(DATA_FOLDER, prot_id, str(seg_id), "simple")) # simple PDB file names (single chain)
    simple_pdbs = [el for el in simple_pdbs if el.endswith(".cif")]

    simple_pdbs_full_path = [f'/static/data/{prot_id}/{seg_id}/simple/{el}' for el in simple_pdbs]
    
    return render_template(
        'structure.html', data = data1, headings = headings, data2 = data2, cc_new = cc_new, colors = colors,
        seg_ress_dict = seg_ress_dict, prot_id = prot_id, seg_id = seg_id, segment_reps = segment_reps,
        first_site_data = first_site_data, bs_table_tooltips = bs_table_tooltips, bs_ress_table_tooltips = bs_ress_table_tooltips,
        pdb2up_dict = pdb2up_dict_converted, up2pdb_dict = up2pdb_dict_converted, seg_stats = seg_stats_converted, entry_name = entry_name,
        simple_pdbs = simple_pdbs_full_path, assembly_pdb_ids = assembly_pdb_ids, prot_atoms_rep = prot_atoms_rep
    )

@app.route('/about')
def about(): # route for about site
    return render_template('about.html')

@app.route('/help')
def help(): # route for help site
    return render_template('help.html')

@app.route('/contact')
def contact(): # route for contact site
    return render_template('contact.html')

@app.route('/get-table', methods=['POST'])
def get_table(): # route to get binding site residues for a given binding site

    lab = request.json.get('label', None)

    prot_id, seg_id, _ = lab.split("_")

    seg_name = prot_id + "_" + seg_id

    seg_ress = pd.read_pickle(os.path.join(RES_TABLES_FOLDER, "{}_ress.pkl".format(seg_name))) # residue data

    seg_ress = seg_ress.fillna("NaN") # pre-processing could also be done before saving the pickle

    site_ress = seg_ress.query('bs_id == @lab')[cc_new]

    site_data = site_ress.to_dict(orient="list")

    #print(site_data)

    return jsonify(site_data)

@app.route('/download-csv')
def download_csv(): # route to download .csv tables

    filepath = request.args.get('filepath', default=None, type=str)

    filepath = filepath.lstrip('/')

    if filepath is None:
        return "Filepath not provided", 400
    
    else:
    
        full_path = os.path.join(BASE_DIR, filepath)

        df = pd.read_pickle(full_path)

        output = df.to_csv(index=False)

        filenameout = filepath.split("/")[-1].split(".")[0] + ".csv"

        return Response(
            output,
            mimetype="text/csv",
            headers={"Content-disposition": "attachment; filename={}".format(filenameout)},
        )

@app.route('/process-model-order', methods=['POST'])
def process_model_order():
    data = request.json
    loaded_order = data['modelOrder'] # this is the order in which files have been loaded by 3DMol.js
    segment_name = data['segmentName'] # name of the segment
    prot_id, seg_id = segment_name.split("_") # extracting protein ID and segment ID
    cxc_in =f'{DATA_FOLDER}/{prot_id}/{seg_id}/simple/{segment_name}_ALL_inf_average_0.5.cxc' # ChimeraX command file
    attr_in =  f'{DATA_FOLDER}/{prot_id}/{seg_id}/simple/{segment_name}_ALL_inf_average_0.5.defattr' # ChimeraX attribute file

    model_order = extract_open_files(cxc_in) # order in which ChimeraX opens files (important for binding site attribute assignment)

    result_tuples, bs_ids = transform_lines2(attr_in, model_order, loaded_order) # binding site attribute data list of tuples

    max_id = max(bs_ids) # maximum binding site ID

    response_data = {
        'resultTuples': result_tuples,
        'maxId': max_id
    }

    return jsonify(response_data) # send jasonified data back to client

@app.route('/get-contacts', methods=['POST'])
def get_contacts():

    data = request.json
    active_model = data['modelData']
    prot_id = data['proteinId']
    seg_id = data['segmentId']
    
    arpeggio_cons = pd.read_pickle(f'{DATA_FOLDER}/{prot_id}/{seg_id}/arpeggio/{active_model}_bio_proc.pkl')

    arpeggio_cons_filt = arpeggio_cons[
        (arpeggio_cons['contact'].apply(lambda x: x != ["proximal"])) &
        (arpeggio_cons['interacting_entities'] == "INTER") &
        (arpeggio_cons['type'] == "atom-atom")
    ].copy()

    json_cons = arpeggio_cons_filt[arpeggio_cols].to_json(orient='records')

    bs_membership = pd.read_pickle(f'{DATA_FOLDER}/example/other/{prot_id}_{seg_id}_ALL_inf_bss_membership.pkl')

    bs_membership_rev = {v: k for k, vs in bs_membership.items() for v in vs}

    struc_ligs = {k: v for k, v in bs_membership_rev.items() if k.startswith(active_model)}

    arpeggio_cons_filt["LIGAND_ID"] = arpeggio_cons_filt.label_comp_id_bgn + "_" + arpeggio_cons_filt.auth_asym_id_bgn + "_" + arpeggio_cons_filt.auth_seq_id_bgn.astype(str)

    #struc_prot_data = list(arpeggio_cons_filt[["label_comp_id_end", "auth_asym_id_end", "auth_seq_id_end"]].drop_duplicates().itertuples(index=False, name=None))

    struc_prot_data = {}
    for k, v in struc_ligs.items():
        ligand_id = "_".join(k.split("_")[1:])
        ligand_site = v
        ligand_rows = arpeggio_cons_filt[arpeggio_cons_filt.LIGAND_ID == ligand_id]
        struc_prot_data[ligand_id] = [
            list(ligand_rows[["label_comp_id_end", "auth_asym_id_end", "auth_seq_id_end"]].drop_duplicates().itertuples(index=False, name=None)),
            ligand_site
        ]

    response_data = {
        'contacts': json_cons,
        'protein': struc_prot_data,
    }

    return jsonify(response_data) # send jasonified data back to client

@app.route('/get-uniprot-mapping', methods=['POST'])
def get_uniprot_mapping(): # route to get UniProt residue and chain mapping for a given pdb
    data = request.json
    pdb_id = data['pdbId']
    prot_id = data['proteinId']
    seg_id = data['segmentId']

    pdb2up_map = load_pickle(f'{DATA_FOLDER}/{prot_id}/{seg_id}/mapping/{pdb_id}_pdb2up.pkl')
    up2pdb_map = load_pickle(f'{DATA_FOLDER}/{prot_id}/{seg_id}/mapping/{pdb_id}_up2pdb.pkl')
    chain2acc_map = load_pickle(f'{DATA_FOLDER}/{prot_id}/{seg_id}/mapping/{pdb_id}_chain2acc.pkl')
    chains_map_df = pd.read_pickle(f'{DATA_FOLDER}/{prot_id}/{seg_id}/mapping/{pdb_id}_bio_chain_remapping.pkl')
    chains_map = dict(zip(chains_map_df["new_auth_asym_id"], chains_map_df["orig_label_asym_id"]))
    
    response_data = {
        'pdb2up': convert_mapping_dict(pdb2up_map),
        'up2pdb': convert_mapping_dict(up2pdb_map),
        'chain2acc': chain2acc_map,
        'chains': chains_map,
    }

    return jsonify(response_data)

@app.route('/download_superposition', methods=['POST'])
def download_superposition():

    data = request.get_json() # Get JSON data from the POST request
    
    prot_id = data.get('proteinId')
    seg_id = data.get('segmentId')

    simple_dir = os.path.join(DATA_FOLDER, prot_id, str(seg_id), "simple")
    simple_pdbs = os.listdir(simple_dir)
    simple_pdbs = [f'{simple_dir}/{el}' for el in simple_pdbs if el.endswith(".cif")]

    seg_name = f'{prot_id}_{seg_id}'
    cxc_in =f'{DATA_FOLDER}/{prot_id}/{seg_id}/simple/{seg_name}_ALL_inf_average_0.5.cxc' # ChimeraX command file
    attr_in =  f'{DATA_FOLDER}/{prot_id}/{seg_id}/simple/{seg_name}_ALL_inf_average_0.5.defattr' # ChimeraX attribute file

    bs_membership = pd.read_pickle(f'{DATA_FOLDER}/example/other/{prot_id}_{seg_id}_ALL_inf_bss_membership.pkl')

    bs_ids = list(bs_membership.keys())
    
    if not prot_id or not seg_id or not simple_pdbs: # Validate the received data
        return jsonify({'error': 'Missing data'}), 400

    # read lines in cxc_in and push to cxc_lines
    cxc_lines = []
    with open(cxc_in, 'r') as file:
        for line in file:
            if line.strip() == '':
                continue
            else:
                cxc_lines.append(line.strip())
                if line.strip().startswith("# colouring"):
                    break

    for el in extra_cxc_lines:
        cxc_lines.append(el)
    
    for bs_id in bs_ids:
        cxc_lines.append((f'col ::binding_site=={bs_id} {colors[bs_id]};'))
    
    cxc_lines.append(f'save {prot_id}_{seg_id}_ALL_inf_average_0.5.cxs;')
    cxc_lines_string = "\n".join(cxc_lines)

    # Create and add in-memory files directly to the zip
    cxc_file = f'{seg_name}_ALL_inf_average_0.5.cxc'
    cxc_file_in_memory = io.BytesIO()
    cxc_file_in_memory.write(cxc_lines_string.encode('utf-8'))

    files_to_zip = simple_pdbs + [attr_in, ]#cxc_in]

    memory_file = io.BytesIO() # Create a BytesIO object to hold the in-memory zip file

    with zipfile.ZipFile(memory_file, 'w') as zf: # Create a ZipFile object for in-memory use
        for file_path in files_to_zip:
            if os.path.exists(file_path):  # Check if the file exists
                zf.write(file_path, os.path.basename(file_path))
            else:
                return f"File {file_path} not found", 404
        
        # Add the in-memory files directly to the in-memory zip
        cxc_file_in_memory.seek(0)
        zf.writestr(cxc_file, cxc_file_in_memory.read())
    
    memory_file.seek(0)  # Seek to the beginning of the BytesIO object before sending it
    
    return send_file( # Send the zip file to the client as a downloadable file
        memory_file,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f'{prot_id}_{seg_id}_superposition.zip'
    )

@app.route('/download_assembly', methods=['POST'])
def download_assembly():
    data = request.get_json() # Get JSON data from the POST request
    
    prot_id = data.get('proteinId')
    seg_id = data.get('segmentId')
    pdb_id = data.get('pdbId')
    
    if not prot_id or not seg_id or not pdb_id: # Validate the received data
        return jsonify({'error': 'Missing data'}), 400

    assembly_file = f'{DATA_FOLDER}/{prot_id}/{seg_id}/assemblies/{pdb_id}_bio.cif' # assembly cif file

    arpeggio_cons = pd.read_pickle(f'{DATA_FOLDER}/{prot_id}/{seg_id}/arpeggio/{pdb_id}_bio_proc.pkl')

    arpeggio_cons_filt = arpeggio_cons[
        (arpeggio_cons['contact'].apply(lambda x: x != ["proximal"])) &
        (arpeggio_cons['interacting_entities'] == "INTER") &
        (arpeggio_cons['type'] == "atom-atom")
    ].copy()

    pseudobond_lines = "\n".join(generate_pseudobond_lines(arpeggio_cons_filt))
    pseudobond_file = f'{prot_id}_{seg_id}_{pdb_id}.pb'

    bs_membership = pd.read_pickle(f'{DATA_FOLDER}/example/other/{prot_id}_{seg_id}_ALL_inf_bss_membership.pkl')

    bs_membership_rev = {v: k for k, vs in bs_membership.items() for v in vs}

    struc_ligs = {k: v for k, v in bs_membership_rev.items() if k.startswith(pdb_id)}

    arpeggio_cons_filt["LIGAND_ID"] = arpeggio_cons_filt.label_comp_id_bgn + "_" + arpeggio_cons_filt.auth_asym_id_bgn + "_" + arpeggio_cons_filt.auth_seq_id_bgn.astype(str)

    struc_prot_data = {}
    for k, v in struc_ligs.items():
        ligand_id = "_".join(k.split("_")[1:])
        ligand_site = v
        ligand_rows = arpeggio_cons_filt[arpeggio_cons_filt.LIGAND_ID == ligand_id]
        struc_prot_data[ligand_id] = [
            list(ligand_rows[["label_comp_id_end", "auth_asym_id_end", "auth_seq_id_end"]].drop_duplicates().itertuples(index=False, name=None)),
            ligand_site
        ]

    aas_str = []

    ligs_str = []

    for k, v in struc_prot_data.items():
        lig_resn, lig_chain, lig_resi = k.split("_")
        ress = v[0]
        col_key = v[1]
        print(k, ress)
        if ress != []:
            prot_sel_str = 'sel ' + ' '.join([f'/{el[1]}:{el[2]}' for el in ress]) + ';'
            prot_col_str = f'col sel {colors[col_key]}'
            prot_disp_str = 'disp sel'
            aas_str.extend([prot_sel_str, prot_col_str, prot_disp_str])

        lig_sel_str = 'sel ' + f'/{lig_chain}:{lig_resi};'
        lig_col_str = f'col sel {colors[col_key]}'
        lig_disp_str = 'disp sel'

        ligs_str.extend([lig_sel_str, lig_col_str, lig_disp_str])

    cxc_lines = "\n".join(
        [
            f'open {pdb_id}_bio.cif',
            'color white', 
            f'open {pseudobond_file}',
            'set bgColor white',
            'set silhouette ON',
            'set silhouettewidth 2',
            '~disp',
            'surface',
            'transparency 30',
        ]  + aas_str + ligs_str + ['~sel']
    )

    cxc_file = f'{prot_id}_{seg_id}_{pdb_id}.cxc'

    info_file = "README.txt"

    files_to_zip = [
        assembly_file, 
    ]

    # Create and add in-memory files directly to the zip
    pb_file_in_memory = io.BytesIO()
    pb_file_in_memory.write(pseudobond_lines.encode('utf-8'))

    cxc_file_in_memory = io.BytesIO()
    cxc_file_in_memory.write(cxc_lines.encode('utf-8'))
        
    info_file_in_memory = io.BytesIO()
    info_file_in_memory.write(contacts_info.encode('utf-8'))
    
    # Create an in-memory zip file for sending to the client
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w') as zf:
        # Add the existing files to the in-memory zip
        for file_path in files_to_zip:
            if os.path.exists(file_path):  # Check if the file exists
                zf.write(file_path, os.path.basename(file_path))
        
        # Add the in-memory files directly to the in-memory zip
        pb_file_in_memory.seek(0)
        zf.writestr(pseudobond_file, pb_file_in_memory.read())

        cxc_file_in_memory.seek(0)
        zf.writestr(cxc_file, cxc_file_in_memory.read())

        info_file_in_memory.seek(0)
        zf.writestr(info_file, info_file_in_memory.read())
    
    # Seek to the beginning of the in-memory zip file before sending it
    memory_file.seek(0)
    
    # Send the zip file to the client as a downloadable file
    return send_file(
        memory_file,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f'{prot_id}_{seg_id}_{pdb_id}_assembly.zip'
    )

@app.route('/download_all_assemblies', methods=['POST'])
def download_all_assemblies():
    data = request.get_json() # Get JSON data from the POST request
    
    prot_id = data.get('proteinId')
    seg_id = data.get('segmentId')
    assembly_pdb_ids = data.get('assemblyPdbIds')  # This is your array

    bs_membership = pd.read_pickle(f'{DATA_FOLDER}/example/other/{prot_id}_{seg_id}_ALL_inf_bss_membership.pkl')

    bs_membership_rev = {v: k for k, vs in bs_membership.items() for v in vs}

    if not prot_id or not seg_id or not assembly_pdb_ids: # Validate the received data
        return jsonify({'error': 'Missing data'}), 400
    
    memory_file = io.BytesIO() # Create an in-memory zip file for sending to the client
    with zipfile.ZipFile(memory_file, 'w') as zf:
        for pdb_id in assembly_pdb_ids: # Loop through each assembly PDB ID to create corresponding folders in the zip
            folder_name = f'{pdb_id}'

            assembly_file = f'{DATA_FOLDER}/{prot_id}/{seg_id}/assemblies/{pdb_id}_bio.cif' # assembly cif file

            arpeggio_cons = pd.read_pickle(f'{DATA_FOLDER}/{prot_id}/{seg_id}/arpeggio/{pdb_id}_bio_proc.pkl')

            arpeggio_cons_filt = arpeggio_cons[
                (arpeggio_cons['contact'].apply(lambda x: x != ["proximal"])) &
                (arpeggio_cons['interacting_entities'] == "INTER") &
                (arpeggio_cons['type'] == "atom-atom")
            ].copy()

            pseudobond_lines = "\n".join(generate_pseudobond_lines(arpeggio_cons_filt))
            pseudobond_file = f'{prot_id}_{seg_id}_{pdb_id}.pb'

            struc_ligs = {k: v for k, v in bs_membership_rev.items() if k.startswith(pdb_id)}

            arpeggio_cons_filt["LIGAND_ID"] = arpeggio_cons_filt.label_comp_id_bgn + "_" + arpeggio_cons_filt.auth_asym_id_bgn + "_" + arpeggio_cons_filt.auth_seq_id_bgn.astype(str)

            struc_prot_data = {}
            for k, v in struc_ligs.items():
                ligand_id = "_".join(k.split("_")[1:])
                ligand_site = v
                ligand_rows = arpeggio_cons_filt[arpeggio_cons_filt.LIGAND_ID == ligand_id]
                struc_prot_data[ligand_id] = [
                    list(ligand_rows[["label_comp_id_end", "auth_asym_id_end", "auth_seq_id_end"]].drop_duplicates().itertuples(index=False, name=None)),
                    ligand_site
                ]

            aas_str = []

            ligs_str = []

            for k, v in struc_prot_data.items():
                lig_resn, lig_chain, lig_resi = k.split("_")
                ress = v[0]
                col_key = v[1]
                if ress != []:
                    prot_sel_str = 'sel ' + ' '.join([f'/{el[1]}:{el[2]}' for el in ress]) + ';'
                    prot_col_str = f'col sel {colors[col_key]}'
                    prot_disp_str = 'disp sel'
                    aas_str.extend([prot_sel_str, prot_col_str, prot_disp_str])

                lig_sel_str = 'sel ' + f'/{lig_chain}:{lig_resi};'
                lig_col_str = f'col sel {colors[col_key]}'
                lig_disp_str = 'disp sel'

                ligs_str.extend([lig_sel_str, lig_col_str, lig_disp_str])

            cxc_lines = "\n".join(
                [
                    f'open {pdb_id}_bio.cif',
                    'color white', 
                    f'open {pseudobond_file}',
                    'set bgColor white',
                    'set silhouette ON',
                    'set silhouettewidth 2',
                    '~disp',
                    'surface',
                    'transparency 30',
                ]  + aas_str + ligs_str + ['~sel']
            )

            cxc_file = f'{prot_id}_{seg_id}_{pdb_id}.cxc'

            info_file = "README.txt"

            files_to_zip = [
                assembly_file, 
            ]

            # Create and add in-memory files directly to the zip
            pb_file_in_memory = io.BytesIO()
            pb_file_in_memory.write(pseudobond_lines.encode('utf-8'))

            cxc_file_in_memory = io.BytesIO()
            cxc_file_in_memory.write(cxc_lines.encode('utf-8'))
            
            for file_path in files_to_zip:
                if os.path.exists(file_path):  # Check if the file exists
                    zf.write(file_path, os.path.join(folder_name, os.path.basename(file_path)))

            # Add the in-memory files directly to the in-memory zip
            pb_file_in_memory.seek(0)
            zf.writestr(os.path.join(folder_name, pseudobond_file), pb_file_in_memory.read())

            cxc_file_in_memory.seek(0)
            zf.writestr(os.path.join(folder_name, cxc_file), cxc_file_in_memory.read())

        info_file_in_memory = io.BytesIO()
        info_file_in_memory.write(contacts_info.encode('utf-8'))

        info_file_in_memory.seek(0)
        zf.writestr(info_file, info_file_in_memory.read())
    
    # Seek to the beginning of the in-memory zip file before sending it
    memory_file.seek(0)
    
    # Send the zip file to the client as a downloadable file
    return send_file(
        memory_file,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f'{prot_id}_{seg_id}_all_assemblies.zip'
    )

### LAUNCHING SERVER ###

if __name__ == "__main__":
    app.run(port = 9000, debug = True) # run Flask LIGYSIS app on port 9000
    
# the end