"""Run only through approved arch.cli build. No external Python dependencies."""
import json
import math
import sys
from pathlib import Path
import bpy
from mathutils import Vector

review_path, output, samples, resolution = sys.argv[sys.argv.index('--')+1:]
review = json.loads(Path(review_path).read_text())
scene_data = review['scene']
out = Path(output)
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
scene = bpy.context.scene
scene.unit_settings.system = 'METRIC'
scene.unit_settings.scale_length = 1


def material(name, color, roughness):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value = (*color, 1)
    bsdf.inputs['Roughness'].default_value = roughness
    return mat


plaster = material('Warm plaster', (.72, .69, .62), .8)
wood = material('Oak', (.3, .15, .065), .38)
fabric = material('Woven sage', (.16, .24, .2), .85)
floor = material('Limestone', (.5, .46, .38), .55)
noise = wood.node_tree.nodes.new('ShaderNodeTexNoise')
noise.inputs['Scale'].default_value = 8
bump = wood.node_tree.nodes.new('ShaderNodeBump')
bump.inputs['Strength'].default_value = .15
bump.inputs['Distance'].default_value = .015
wood.node_tree.links.new(noise.outputs['Fac'], bump.inputs['Height'])
wood.node_tree.links.new(bump.outputs['Normal'], wood.node_tree.nodes.get('Principled BSDF').inputs['Normal'])


def cube(name, center, dimensions, mat, bevel=0):
    bpy.ops.mesh.primitive_cube_add(size=1, location=center)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = dimensions
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(mat)
    if bevel:
        mod = obj.modifiers.new('Soft furniture edges', 'BEVEL')
        mod.width = bevel
        mod.segments = 3
    return obj


for i, part in enumerate(scene_data['solids']):
    x0, y0, x1, y1 = part['bounds']
    z0, z1 = part['z0'], part['z1']
    obj = cube(f'Wall_{part["source"]}_{i}', ((x0+x1)/2, (y0+y1)/2, (z0+z1)/2), (x1-x0, y1-y0, z1-z0), plaster)
    obj['dxf_handle'] = part['source']
for room in (r for r in scene_data['records'] if r['kind'] == 'room'):
    x0,y0,x1,y1 = room['bounds']
    thick = scene_data['slab_thickness']
    obj = cube('Floor_'+room['id'], ((x0+x1)/2,(y0+y1)/2,-thick/2), (x1-x0,y1-y0,thick), floor)
    obj['dxf_handle'] = room['id']

for index, item in enumerate(review['furniture']):
    angle = math.radians(item['rotation'])
    def component(label, x, y, z, w, d, h, mat):
        px = item['x'] + x*math.cos(angle)-y*math.sin(angle)
        py = item['y'] + x*math.sin(angle)+y*math.cos(angle)
        obj = cube(f'{item["asset"]}_{index}_{label}', (px,py,z), (w,d,h), mat, .015)
        obj.rotation_euler.z = angle
        obj['design_proposal'] = True
    if item['asset'] == 'table':
        component('top',0,0,.42,1.1,.6,.06,wood)
        for x in (-.45,.45):
            for y in (-.2,.2):
                component('leg',x,y,.2,.05,.05,.4,wood)
    else:
        w,d = (2,.85) if item['asset'] == 'sofa' else (.6,.6)
        component('base',0,0,.22,w,d,.32,wood)
        component('seat',0,-.04,.44,w-.08,d-.12,.12,fabric)
        component('back',0,d/2-.07,.66,w,.14,.38,fabric)

bounds = [r['bounds'] for r in scene_data['records'] if r['kind'] == 'room']
x0,y0 = min(b[0] for b in bounds),min(b[1] for b in bounds)
x1,y1 = max(b[2] for b in bounds),max(b[3] for b in bounds)
center = Vector(((x0+x1)/2,(y0+y1)/2,0))
span = max(x1-x0,y1-y0)
bpy.ops.object.camera_add(location=(center.x+span*.65,center.y-span*.9,span*1.45))
camera = bpy.context.object
camera.rotation_euler = (center-camera.location).to_track_quat('-Z','Y').to_euler()
camera.data.type = 'ORTHO'
camera.data.ortho_scale = span*1.7
scene.camera = camera
world = bpy.data.worlds.new('Studio daylight')
world.use_nodes = True
world.node_tree.nodes['Background'].inputs[0].default_value = (.65,.75,1,1)
world.node_tree.nodes['Background'].inputs[1].default_value = .35
scene.world = world
bpy.ops.object.light_add(type='AREA', location=(center.x,center.y,scene_data['wall_height']+3))
bpy.context.object.data.energy = 1800
bpy.context.object.data.shape = 'DISK'
bpy.context.object.data.size = span*.8
scene.render.engine = 'CYCLES'
scene.cycles.device = 'CPU'
scene.cycles.samples = int(samples)
scene.cycles.use_denoising = True
scene.cycles.seed = 42
scene.render.resolution_x = scene.render.resolution_y = int(resolution)
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'PNG'
scene.render.filepath = str(out/'render.png')
bpy.ops.wm.save_as_mainfile(filepath=str(out/'model.blend'))
bpy.ops.render.render(write_still=True)
(out/'manifest.json').write_text(json.dumps({'blender': bpy.app.version_string,
    'source_sha256': scene_data['source_sha256'], 'wall_parts':len(scene_data['solids']),
    'furniture_count':len(review['furniture']), 'render':'Cycles CPU', 'samples':int(samples),
    'limitations':'Open ceiling; schematic procedural furniture; no inferred assemblies'},indent=2))
