let element = document.querySelector('#container-01');

let config = {
    //antialias: true,
    // backgroundAlpha: 0.5,
    backgroundColor: 'white',
    // /canvas: "webgl",
    // cartoonQuality: 10,
    // disableFog: true,
    id: "3DmolCanvas",
} 

let viewer = $3Dmol.createViewer( element, config );

$3Dmol.setSyncSurface(true); // all surfaces appear at once

// viewer.setViewStyle({'style': 'outline', 'color': 'black','width': 0.1})

// let pdbUri = `/static/data/biolip/split/structures/${segmentReps[segmentId]["rep"]}.pdb`;

let pdbUri = `/static/data/biolip/split/structures/cif/${repStruc}.cif`;
jQuery.ajax( pdbUri, { 
    success: function(data) {
        viewer.addModel( data, "cif" );                       /* load data */
        viewer.setStyle(
            {}, /* style all atoms */
            {
                cartoon: {
                    style:'oval', color: 'white', arrows: true,
                }
            }
        );  
        viewer.zoomTo();                                      /* set camera */
        viewer.render({});                                    /* render scene */
        viewer.zoom(1.2, 100);                                /* slight zoom */
    },
    error: function(hdr, status, err) {
        console.error( "Failed to load PDB " + pdbUri + ": " + err );
    },
});

viewer.resize();