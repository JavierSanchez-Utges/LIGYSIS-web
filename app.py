### PACKAGE IMPORTS ###

import os
import re
import io
import csv
import pickle
import numpy as np
import pandas as pd

from flask import Flask, render_template, url_for, request, redirect, jsonify, Response

from config import BASE_DIR, DATA_FOLDER, SITE_TABLES_FOLDER, RES_TABLES_FOLDER, REP_STRUCS_FOLDER, BS_RESS_FOLDER, MAPPINGS_FOLDER, STATS_FOLDER, ENTRY_NAMES_FOLDER

### VARIABLES ###

arpeggio_cols = [
    'contact', 'distance',
    'auth_asym_id_end', 'auth_atom_id_end', 'auth_seq_id_end',
    'label_comp_id_end', 'auth_asym_id_bgn',
    'auth_atom_id_bgn', 'auth_seq_id_bgn', 'label_comp_id_bgn',
    'orig_label_asym_id_end', 'UniProt_ResNum_end',
    'coords_end', 'coords_bgn', 'width', 'color'
]

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

### READING INPUT DATA ###

prot_ids = load_pickle(os.path.join(DATA_FOLDER, "biolip_up_ids_15000_accs.pkl")) # protein idshon

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

    # print(bss_data.shape)

    bss_prot = bss_data[bss_data.ID.str.contains(seg_name)].copy() # extracting Segment of interest rows from table

    bss_prot.ID = bss_prot.ID.str.split("_").str[2] # extracting binding site ID from binding site name, which is UniProt ID _ Segment ID _ Binding Site ID

    bss_prot.ID = bss_prot.ID.astype(int) # changing binding site ID to integer data type

    bss_prot = bss_prot.sort_values(by = "ID") # sorting binding site table rows by ID

    first_site = bss_prot.ID.unique().tolist()[0] # first binding site ID

    first_site_name = seg_name + "_" + str(first_site) # name of first binding site (data shown by default when oppening page)

    bss_ress = pd.read_pickle(os.path.join(RES_TABLES_FOLDER, "{}_ress.pkl".format(seg_name))) # residue data
    bss_ress = bss_ress.fillna("NaN") # pre-processing could also be done before saving the pickle

    # print(bss_ress.shape)

    first_site_data = bss_ress.query('bs_id == @first_site_name')[cc_new].to_dict(orient="list") # data of first binding site residues

    # print(bss_prot)

    data1 = bss_prot.to_dict(orient="list") # converting table to dictionary to pass to client

    # print(data1)

    prot_ress = bss_ress.query('up_acc == @prot_id')[cc_new]

    prot_seg_rep_strucs = load_pickle(os.path.join(REP_STRUCS_FOLDER, "{}_segs_rep_strucs.pkl".format(prot_id))) # representative structures dict (only successfully run segments)

    segment_reps = prot_seg_rep_strucs[prot_id]

    # segment_reps = dict(sorted(segment_reps.items())) # should not be necessary since I sorted it beforehand

    data2 = prot_ress.to_dict(orient="list")

    #bs_ress_dict = load_pickle(os.path.join(BS_RESS_FOLDER, "{}_bs_ress.pkl".format(prot_id)))
    bs_ress_dict = load_pickle(os.path.join(DATA_FOLDER, "example", "other", f'{prot_id}_{seg_id}_ALL_inf_bss_ress.pkl'))

    seg_ress_dict = bs_ress_dict#[prot_id][seg_id]
    seg_ress_dict = {str(key): value for key, value in seg_ress_dict.items()}
    # add key: "ALL_BINDING" and value a sorted set of all binding residues
    seg_ress_dict["ALL_BINDING"] = sorted(list(set([el2 for el in seg_ress_dict.values() for el2 in el])))
    # print(seg_ress_dict)

    pdb2up_dict = load_pickle(os.path.join(MAPPINGS_FOLDER, "pdb2up", "{}_pdb2up_mapping.pkl".format(segment_reps[int(seg_id)]["rep"])))

    up2pdb_dict = load_pickle(os.path.join(MAPPINGS_FOLDER, "up2pdb", "{}_up2pdb_mapping.pkl".format(segment_reps[int(seg_id)]["rep"])))

    seg_stats = load_pickle(os.path.join(STATS_FOLDER, "{}_stats.pkl".format(seg_name)))

    entry_name = load_pickle(os.path.join(ENTRY_NAMES_FOLDER, "{}_name.pkl".format(prot_id)))[prot_id]

    # for v in seg_stats[prot_id][seg_id].values():
    #     v = int(v)
    
    seg_stats_converted = convert_numpy(seg_stats) # converting data type of Segment summary statistics

    up2pdb_dict_converted = {k: {k2:{int(k3):int(v3) for k3, v3 in v2.items()} for k2, v2 in v.items()} for k, v in up2pdb_dict.items()}

    pdb2up_dict_converted = {k: {k2:{int(k3):int(v3) for k3, v3 in v2.items()} for k2, v2 in v.items()} for k, v in pdb2up_dict.items()}

    assembly_pdbs = os.listdir(os.path.join(DATA_FOLDER, prot_id, str(seg_id), "assemblies")) # CIF bio assembly file names
    assembly_pdbs = [el for el in assembly_pdbs if el.endswith(".cif")]

    assembly_pdb_ids = sorted(list(set([el.split("_")[0] for el in assembly_pdbs])),) # sorted unique PDB IDs

    simple_pdbs = os.listdir(os.path.join(DATA_FOLDER, prot_id, str(seg_id), "simple")) # simple PDB file names (single chain)
    simple_pdbs = [el for el in simple_pdbs if el.endswith(".cif")]

    simple_pdbs_full_path = [f'/static/data/{prot_id}/{seg_id}/simple/{el}' for el in simple_pdbs]

    # print(assembly_pdb_ids)
    
    return render_template(
        'structure.html', data = data1, headings = headings, data2 = data2, cc_new = cc_new, colors = colors,
        seg_ress_dict = seg_ress_dict, prot_id = prot_id, seg_id = seg_id, segment_reps = segment_reps,
        first_site_data = first_site_data, bs_table_tooltips = bs_table_tooltips, bs_ress_table_tooltips = bs_ress_table_tooltips,
        pdb2up_dict = pdb2up_dict_converted, up2pdb_dict = up2pdb_dict_converted, seg_stats = seg_stats_converted, entry_name = entry_name,
        simple_pdbs = simple_pdbs_full_path, assembly_pdb_ids = assembly_pdb_ids
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

    #struc_ligs_data = transform_dict(struc_ligs)

    arpeggio_cons_filt["LIGAND_ID"] = arpeggio_cons_filt.label_comp_id_bgn + "_" + arpeggio_cons_filt.auth_asym_id_bgn + "_" + arpeggio_cons_filt.auth_seq_id_bgn.astype(str)

    #print(arpeggio_cons_filt)

    struc_prot_data = list(arpeggio_cons_filt[["label_comp_id_end", "auth_asym_id_end", "auth_seq_id_end"]].drop_duplicates().itertuples(index=False, name=None))

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
        #'ligands': struc_ligs_data,
        'protein': struc_prot_data,
    }

    # print(struc_ligs)
    # print(len(json_cons))
    # print(len(struc_ligs_data))
    # print(struc_ligs_data)
    # print(len(struc_prot_data))
    #print(struc_prot_data)

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

### LAUNCHING SERVER ###

if __name__ == "__main__":
    app.run(port = 9000, debug = True) # run Flask LIGYSIS app on port 9000
    
# the end