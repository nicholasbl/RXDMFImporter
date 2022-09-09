bl_info = {
    "name": "Rich XDMF Importer",
    "author": "Nicholas Brunhart-Lupo",
    "version": (0, 1),
    "blender": (3, 1, 0),
    "category": "Import-Export",
    "location": "File > Import > RXDMF (.xmf)",
    "description": "Import XDMF files, with matching attributes",
    "warning": "This is an experimental version, and is not feature complete",
    "doc_url": "",
    "tracker_url": "",
}


import bpy
from bpy.types import Operator
from bpy_extras.io_utils import ImportHelper

import numpy as np

import xml.etree.ElementTree as ET

import logging
import os
import time

log = logging.getLogger(__name__)

#logging.basicConfig(level=logging.INFO)

class XDMFImportError(Exception):
    pass

class XDMFImporter():
    def __init__(self):
        self.file_dir = None
        self.file = None
        
    def resolve(self, fname):
        fname = fname.strip()
        if os.path.exists(fname): return fname
    
        fname = str(os.path.basename(fname))
        log.info(f"Unable to find {fname} as absolute path, trying search")
        
        for root, dirs, files in os.walk(self.file_dir):
            if fname in files: 
                return os.path.join(root, fname)
            
        raise XDMFImportError("Unable to find data file")
            
    def convert_format(self, f, p):
        if f == "Float":
            if p == 4: return np.float32
            if p == 8: return np.float64
            return np.float32
        
        if f == "Int":
            if p == 8: return np.int64
            return np.int32
        
        return np.float32
    
    def get_data(self, di_node):
        format = di_node.attrib["Format"] 
        precision = int(di_node.attrib.get("Precision",-1))
        data_type = di_node.attrib["DataType"]
        seek = int(di_node.attrib.get("Seek",0))
        dims = int(di_node.attrib.get("Dimensions",0))
        
        log.info(f"Data with format {format} {precision} {data_type} {seek}")
        
        if format == "Binary":
            file_path = self.resolve(di_node.text)
            ntype = self.convert_format(data_type, precision)
            
            src = np.memmap(file_path, ntype, mode='r', offset=seek, shape=(dims))
            
            return src
        
        raise XDMFImportError("Non-binary files are unsupported at this time") 


    def import_connectivity(self, topo_node):
        if topo_node.attrib["TopologyType"] != "Triangle":
            raise XDMFImportError()
            
        conn_count = int(topo_node.attrib["NumberOfElements"])
            
        data = topo_node.find("DataItem")
        
        if data.attrib["Name"] != "Conn": 
            raise XDMFImportError()
            
        conn_data = self.get_data(data)
        
        conn_data = np.reshape(conn_data, (conn_count, -1))
        
        return conn_data
    
    def import_geometry(self, geom_node):
        if geom_node.get("GeometryType") != "XYZ":
            raise XDMFImportError("Unknown geometry type")
            
        for data in geom_node.iter("DataItem"):
            if data.attrib["Name"] != "Coord": 
                continue
            
            geom_data = self.get_data(data)
            
            return np.reshape(geom_data, (-1, 3))
            
        raise XDMFImportError("Missing coordinate information")
        

    def import_grid(self, gnode):
        tnode = gnode.find("Time")
        topo = gnode.find("Topology")
        geom = gnode.find("Geometry")
        
        for v in [tnode, topo, geom]:
            if v is None: raise XDMFImportError()
        
        log.info("Importing time:", tnode.attrib["Value"])
        
        conn_array = self.import_connectivity(topo)
        geom_array = self.import_geometry(geom)
        
        name = gnode.get("Name", os.path.splitext(self.file)[0])
        
        new_mesh = bpy.data.meshes.new(name+"_mesh")
        
        new_mesh.from_pydata(geom_array, [], conn_array)
        

        
        for att in gnode.iter("Attribute"):
            att_name = att.get("Name")
            att_type = att.get("AttributeType")
            att_center = att.get("Center")
            
            att_data = att.find("DataItem")
            
            if att_data is None: 
                raise XDMFImportError("Missing attribute data")
            
            att_data = self.get_data(att_data).astype(np.float32)
            
            if att_type != "Scalar" or att_center != "Node":
                log.warn("Unsupported attribute format {att_type} {att_center}, att_skipping...")
                continue
                
            log.info(f"Adding attribute {att_name} {att_type} {att_center} {len(att_data)}")
            
            battr = new_mesh.attributes.new(att_name, 'FLOAT', 'POINT')
            battr.data.foreach_set("value", att_data)
            
        new_mesh.update()
        
        new_object = bpy.data.objects.new(name, new_mesh)
        
        scene = bpy.context.scene
        scene.collection.objects.link(new_object)
        
        bpy.ops.object.select_all(action='DESELECT')
        new_object.select_set(True)
            
        

    def import_domain(self, dnode):
        for n in dnode.iter("Grid"):
            self.import_grid(n)

    def import_xdmf(self, fname):
        log.info(f"Trying to load {fname}...")
        fname = os.path.abspath(fname)
        
        self.file = os.path.basename(fname)
        self.file_dir = os.path.dirname(fname)
        
        log.debug("Containing dir", self.file_dir)
        
        parser = ET.parse(fname)
        
        root = parser.getroot()
        
        assert(root.tag == "Xdmf")
        
        assert(float(root.attrib['Version']) >= 3)
        
        for n in root.iter("Domain"):
            self.import_domain(n)
        
class ImportXMDF(Operator, ImportHelper):
    "Load a rich XDMF file"
    
    bl_idname = "xdmf_import.import_file"
    bl_label = "Import Rich XDMF"
    
    filename_ext = "*.xmf"
    
    def execute(self, context):
        
        start_import = time.time()
        
        importer = XDMFImporter()
        
        importer.import_xdmf(self.filepath)
        
        end_import = time.time()
        
        delta = round(end_import - start_import, 2)
        
        log.info(f"Done importing: {delta}s")
        
        return {"FINISHED"}
    
classes = [
    ImportXMDF
]

def menu_function_import(self, context):
    self.layout.operator(ImportXMDF.bl_idname, text = "RXDMF (.xmf)")

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
        
    bpy.types.TOPBAR_MT_file_import.append(menu_function_import)

def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_function_import)
    
    for cls in classes:
        bpy.utils.unregister_class(cls)
        
if __name__ == "__main__":
    register()
