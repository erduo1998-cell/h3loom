"""H3Loom film v2. Procedural geometry, materials, lighting and animation.

Run in a fresh Blender process, never against a user's open scene.
blender -b --factory-startup --python film.py -- --stills
blender -b --factory-startup --python film.py -- --start 0 --end 720
"""
import argparse
import math
import os
from pathlib import Path
import sys

import bpy
from mathutils import Vector

args = argparse.ArgumentParser()
args.add_argument('--stills', action='store_true')
args.add_argument('--start', type=int, default=0)
args.add_argument('--end', type=int, default=720)
args.add_argument('--scale', type=int, default=100)
args.add_argument('--samples', type=int, default=24)
args.add_argument('--engine', choices=['cycles','eevee'], default='cycles')
args.add_argument('--out', default='promo-v2')
opts = args.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
OUT = Path(__file__).resolve().parents[2] / 'outputs' / opts.out
OUT.mkdir(parents=True, exist_ok=True)
FPS = 30
scene = bpy.context.scene
scene.render.engine = 'CYCLES'
scene.cycles.samples = opts.samples
scene.cycles.use_denoising = True
if sys.platform == 'darwin' and opts.engine == 'cycles':
    prefs = bpy.context.preferences.addons['cycles'].preferences
    prefs.compute_device_type = 'METAL'
    prefs.get_devices()
    for device in prefs.devices:
        device.use = device.type == 'METAL'
    scene.cycles.device = 'GPU'
if opts.engine == 'eevee':
    scene.render.engine = 'BLENDER_EEVEE'
    scene.eevee.taa_render_samples = 48
    scene.eevee.use_raytracing = True
scene.cycles.max_bounces = 5
scene.render.use_persistent_data = True
scene.render.resolution_x = 1920
scene.render.resolution_y = 1080
scene.render.resolution_percentage = opts.scale
scene.render.fps = FPS
scene.render.image_settings.file_format = 'PNG'
scene.render.film_transparent = False
scene.view_settings.view_transform = 'AgX'
scene.view_settings.look = 'AgX - Medium High Contrast'
scene.world.use_nodes = True
scene.world.node_tree.nodes['Background'].inputs['Color'].default_value = (0, 0, 0, 1)
scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)

FONT = bpy.data.fonts.load(os.environ.get('H3LOOM_FILM_FONT', '/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf'))
REGULAR = bpy.data.fonts.load(os.environ.get('H3LOOM_LABEL_FONT', '/System/Library/Fonts/Supplemental/Arial.ttf'))

def material(name, color, metallic=0, roughness=.35, emission=0):
    m = bpy.data.materials.new(name)
    m.diffuse_color = (*color, 1)
    m.use_nodes = True
    p = m.node_tree.nodes.get('Principled BSDF')
    p.inputs['Base Color'].default_value = (*color, 1)
    p.inputs['Metallic'].default_value = metallic
    p.inputs['Roughness'].default_value = roughness
    if emission:
        p.inputs['Emission Color'].default_value = (*color, 1)
        p.inputs['Emission Strength'].default_value = emission
    return m

silver = material('Anodised aluminium - satin face', (.48, .49, .52), .92, .40)
nodes = silver.node_tree.nodes
noise = nodes.new('ShaderNodeTexNoise')
noise.inputs['Scale'].default_value = 950
noise.inputs['Detail'].default_value = 2
bump = nodes.new('ShaderNodeBump')
bump.inputs['Strength'].default_value = .075
bump.inputs['Distance'].default_value = .006
silver.node_tree.links.new(noise.outputs['Fac'], bump.inputs['Height'])
silver.node_tree.links.new(bump.outputs['Normal'], nodes['Principled BSDF'].inputs['Normal'])
edge = material('Diamond-cut polished edge', (.70, .72, .76), 1, .13)
black = material('Obsidian enamel', (.006, .008, .012), .65, .13)
dark = material('Graphite carrier', (.013, .014, .019), .8, .32)
white = material('Soft silver type', (.60, .62, .65), .8, .26)
glow = material('Indigo signal', (.018, .005, .35), .45, .22, 4)
ink = material('Quiet white labels', (.65, .67, .71), .15, .35, .5)

# Travelling reflectance field: local blue/pink highlights move across type,
# independently of its transform. Fine bevels still respond to real area lights.
iridescent = material('Cobalt violet interference', (.06, .025, .35), 1, .32)
nt = iridescent.node_tree
tex = nt.nodes.new('ShaderNodeTexNoise')
tex.noise_dimensions = '4D'
tex.inputs['Scale'].default_value = 1.65
tex.inputs['Detail'].default_value = 1.1
tex.inputs['Roughness'].default_value = .35
ramp = nt.nodes.new('ShaderNodeValToRGB')
ramp.color_ramp.elements.remove(ramp.color_ramp.elements[1])
colors = [(0, (.007, .009, .06, 1)), (.28, (.022, .024, .24, 1)),
          (.46, (.045, .025, .48, 1)), (.60, (.25, .10, .32, 1)),
          (.72, (.65, .39, .30, 1)), (1, (.92, .80, .66, 1))]
for i, (position, color) in enumerate(colors):
    e = ramp.color_ramp.elements[0] if i == 0 else ramp.color_ramp.elements.new(position)
    e.position, e.color = position, color
nt.links.new(tex.outputs['Fac'], ramp.inputs['Fac'])
nt.links.new(ramp.outputs['Color'], nt.nodes['Principled BSDF'].inputs['Base Color'])

def point(obj, target):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat('-Z', 'Y').to_euler()

def area(name, loc, power, size, color=(1, 1, 1), size_y=None):
    d = bpy.data.lights.new(name, 'AREA')
    d.energy, d.shape, d.size, d.color = power, 'RECTANGLE', size, color
    d.size_y = size_y or size
    ob = bpy.data.objects.new(name, d)
    scene.collection.objects.link(ob)
    ob.location = loc
    point(ob, (0, 0, 0))
    return ob

key = area('Moving broad softbox', (-3, 4, 8), 1150, 7, size_y=4)
strip = area('Long edge reflection', (5, -1, 5), 480, 1.4, size_y=7)
fill = area('Low fill', (-5, -3, 3), 260, 4, (.68, .73, 1), 3)
rim = area('Violet side bounce', (4, 3, 1), 550, 3, (.16, .045, 1), 6)
bpy.ops.object.camera_add(location=(0, 0, 20))
camera = bpy.context.object
camera.name = 'Motion camera'
camera.data.type = 'PERSP'
camera.data.lens = 52
scene.camera = camera
point(camera, (0, 0, 0))

groups = {}
current = None
def group(name):
    global current
    c = bpy.data.collections.new(name)
    scene.collection.children.link(c)
    groups[name] = c
    current = c

def move_group(ob):
    for c in list(ob.users_collection):
        c.objects.unlink(ob)
    current.objects.link(ob)
    return ob

def empty(name):
    ob = bpy.data.objects.new(name, None)
    current.objects.link(ob)
    return ob

def cube(name, loc, dims, mat, bevel=.04, parent=None):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    ob = move_group(bpy.context.object)
    ob.name = name
    ob.dimensions = dims
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    ob.data.materials.append(mat)
    if bevel:
        b = ob.modifiers.new('Machined corner radius', 'BEVEL')
        b.width, b.segments = bevel, 6
        ob.modifiers.new('Weighted surface normals', 'WEIGHTED_NORMAL')
    for p in ob.data.polygons:
        p.use_smooth = True
    ob.parent = parent
    return ob

def text(body, x, y, width, height, mat=white, z=0, parent=None, regular=False):
    d = bpy.data.curves.new(body, 'FONT')
    d.body, d.font, d.size = body, REGULAR if regular else FONT, 1
    d.space_character = 1.01
    d.extrude, d.bevel_depth, d.bevel_resolution = .010, .003, 4
    d.resolution_u = 16
    ob = bpy.data.objects.new(body, d)
    current.objects.link(ob)
    d.materials.append(mat)
    bpy.context.view_layer.update()
    bounds = [Vector(v) for v in ob.bound_box]
    lo = Vector(tuple(min(v[i] for v in bounds) for i in range(3)))
    hi = Vector(tuple(max(v[i] for v in bounds) for i in range(3)))
    ob.scale = (width / (hi.x-lo.x), height / (hi.y-lo.y), 1)
    ob.location = (x - (hi.x+lo.x)/2*ob.scale.x, y - (hi.y+lo.y)/2*ob.scale.y, z)
    bpy.ops.object.select_all(action='DESELECT')
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.convert(target='MESH')
    for polygon in ob.data.polygons:
        polygon.use_smooth = False
    ob.parent = parent
    return ob

def trace(points, mat=glow, radius=.008):
    d = bpy.data.curves.new('Signal trace', 'CURVE')
    d.dimensions = '3D'
    d.bevel_depth, d.bevel_resolution = radius, 2
    p = d.splines.new('POLY')
    p.points.add(len(points)-1)
    for dest, src in zip(p.points, points): dest.co = (*src, 1)
    ob = bpy.data.objects.new('Signal trace', d)
    current.objects.link(ob)
    d.materials.append(mat)
    return ob

group('hero')
hero = empty('Cloud module motion')
cube('Polished thin perimeter', (0, 0, 0), (5.7, 5.7, .86), edge, .31, hero)
cube('Satin silver top', (0, 0, .16), (5.68, 5.68, .68), silver, .30, hero)
cube('Inset graphite underbody', (0, 0, -.42), (5.31, 5.31, .21), dark, .22, hero)
text('H3', 0, .14, 2.20, 1.45, black, .51, hero)
text('L O O M', 0, -.97, 1.53, .16, black, .508, hero, True)
for i in range(33):
    cube('Underside ventilation', (-2.28+i*.143, -2.815, -.12), (.056, .025, .20), black, .022, hero)
cube('Status diode', (2.35, -2.80, .06), (.06, .035, .025), ink, .012, hero)

group('type')
type_root = empty('Type choreography')
type_objects = {}
for word, width, height in [('SRT', 11.6, 6.4), ('DESIGN', 11.8, 5.7), ('RENDER', 11.8, 6.2), ('H3LOOM', 12.2, 5.5), ('4K', 10, 6.2)]:
    type_objects[word] = text(word, 0, 0, width, height, iridescent if word in ('RENDER','4K') else white, parent=type_root)

group('chip')
chip = empty('Cloud engine')
cube('Engine socket', (0,0,-.22), (5.4,5.4,.5), dark, .06, chip)
cube('Die edge', (0,0,.07), (4.6,4.6,.16), edge, .025, chip)
cube('Violet silicon face', (0,0,.18), (4.5,4.5,.15), iridescent, .018, chip)
text('H3', 0, .25, 2.5, 1.55, white, .28, chip)
text('CLOUD RUNTIME', 0, -1.0, 2.65, .20, ink, .28, chip, True)
for side in range(4):
    a = side*math.pi/2
    for i in range(24):
        y = -2.15+i*.185
        pts = [(2.5,y,-.12),(3.1+abs(y)*.5,y,-.12),(4.5+abs(y)*.5,y*1.6,-.12),(11,y*1.6,-.12)]
        points = [(x*math.cos(a)-y*math.sin(a), x*math.sin(a)+y*math.cos(a),z) for x,y,z in pts]
        tr=trace(points, glow if i%5 == 0 else edge, .006)
        tr.parent=chip

# A vertical material-reveal connects wireframe planning to the solid runtime.
# Keep this material change local to the chip; title reflections remain independent.
reveal_controls=[]
chip_materials={}
for ob in list(groups['chip'].objects):
    if not hasattr(ob.data,'materials'): continue
    for idx,base in enumerate(ob.data.materials):
        if base.name not in chip_materials:
            mat=base.copy()
            mat.name=base.name+' / progressive runtime surface'
            tree=mat.node_tree
            output=tree.nodes.get('Material Output')
            source=output.inputs['Surface'].links[0].from_socket
            geometry=tree.nodes.new('ShaderNodeNewGeometry')
            separate=tree.nodes.new('ShaderNodeSeparateXYZ')
            compare=tree.nodes.new('ShaderNodeMath'); compare.operation='GREATER_THAN'
            transparent=tree.nodes.new('ShaderNodeBsdfTransparent')
            mix=tree.nodes.new('ShaderNodeMixShader')
            tree.links.new(geometry.outputs['Position'],separate.inputs[0])
            tree.links.new(separate.outputs['Y'],compare.inputs[0])
            tree.links.new(compare.outputs[0],mix.inputs[0])
            tree.links.new(source,mix.inputs[1])
            tree.links.new(transparent.outputs[0],mix.inputs[2])
            tree.links.new(mix.outputs[0],output.inputs['Surface'])
            reveal_controls.append(compare.inputs[1])
            chip_materials[base.name]=mat
        ob.data.materials[idx]=chip_materials[base.name]
wire=material('Runtime blueprint lines',(.22,.25,.30),0,.6,1)
wire_objects=[]
for size,z in [(5.4,.07),(4.6,.28),(4.42,.30)]:
    r=size/2
    ob=trace([(-r,-r,z),(r,-r,z),(r,r,z),(-r,r,z),(-r,-r,z)],wire,.006)
    ob.parent=chip;wire_objects.append(ob)
for i in range(12):
    x=-2.0+i*.36
    ob=trace([(x,1.72,.31),(x,2.09,.31),(x+.22,2.09,.31),(x+.22,1.72,.31)],wire,.004)
    ob.parent=chip;wire_objects.append(ob)

group('boards')
boards = empty('Storyboard cascade')
cards=[]
for i in range(4):
    root = empty('Storyboard '+str(i+1))
    root.parent = boards
    cards.append(root)
    cube('Storyboard glass edge', (0,0,0), (5.25,3.15,.10), edge, .09, root)
    cube('Storyboard face', (0,0,.065), (5.15,3.05,.04), dark, .06, root)
    text('0'+str(i+1), -2.13, 1.19, .32, .33, white, .16, root)
    text(['ESTABLISH','ROTATE','DETAIL','RESOLVE'][i], .15,-1.28, 1.65,.19, ink,.16,root,True)

group('grid')
grid=empty('Precision composition grid')
text('FROM', -3.78,2.02,4.15,2.45,white,parent=grid)
text('SRT', 2.25,2.02,6.94,2.45,white,parent=grid)
text('TO', -4.10,-.67,3.57,2.62,white,parent=grid)
text('4K', 1.86,-.67,7.7,2.62,iridescent,parent=grid)
text('YOUR STORY. YOUR PIPELINE.',0,-2.65,11.4,.50,white,parent=grid)

def ease(x):
    x=max(0,min(1,x)); return 1-(1-x)**4
def smooth(x):
    x=max(0,min(1,x)); return x*x*(3-2*x)
def lerp(a,b,x): return a+(b-a)*x

def set_time(t):
    for c in groups.values(): c.hide_render=True
    for ob in type_objects.values(): ob.hide_render=True
    camera.location=(0,0,20)
    camera.data.lens=52
    point(camera,(0,0,0))
    key.location=(-3+1.4*math.sin(t*1.9),4,8)
    point(key,(0,0,0))
    strip.location=(5*math.cos(t*.8),-1+2*math.sin(t),5)
    point(strip,(0,0,0))
    rim.data.energy=400
    tex.inputs['W'].default_value=t*.85
    type_root.location=(0,0,0)
    type_root.scale=(1,1,1)
    type_root.rotation_euler=(0,0,0)
    def show_type(word):
        groups['type'].hide_render=False
        type_objects[word].hide_render=False
    if t < 2.6:
        groups['hero'].hide_render=False
        e=smooth((t-.62)/1.0)
        hero.rotation_euler=(lerp(0,.72,e),lerp(0,-.38,e),lerp(0,.40,e))
        s=lerp(.77,1.25,e)+.05*t
        hero.scale=(s,s,s)
        camera.location.z=20-1.5*max(0,t-1.8)
    elif t < 3.35:
        show_type('SRT')
        a=t-2.6
        type_root.scale=(1+ .08*smooth(a/.65),1,1)
    elif t < 4.6:
        show_type('DESIGN')
        a=t-3.35
        type_root.scale=(lerp(.68,1,ease(a/.24)),lerp(1.4,1,ease(a/.24)),1)
        if a>.93:
            s=lerp(1,.21,ease((a-.93)/.32))
            type_root.scale=(s,s,s)
    elif t < 7.4:
        groups['boards'].hide_render=False
        a=t-4.6
        for i,card in enumerate(cards):
            e=ease((a-i*.12)/.62)
            card.location=(lerp(0,(-1 if i%2==0 else 1)*2.82,e),lerp(0,(1 if i<2 else -1)*1.79,e),lerp(i*.32,0,e))
            card.rotation_euler=(lerp(.6,0,e),lerp(-.3,0,e),0)
        boards.rotation_euler=(0, .06*math.sin(a),0)
        if a>2.1:
            p=smooth((a-2.1)/.7)
            camera.location=(2.82*p,1.79*p,lerp(20,2,p))
            point(camera,(2.82*p,1.79*p,0))
    elif t < 8.45:
        show_type('RENDER')
        a=t-7.4
        type_root.scale=(lerp(.91,1,ease(a/.15)),1,1)
    elif t < 12.4:
        groups['chip'].hide_render=False
        a=t-8.45
        for control in reveal_controls: control.default_value=lerp(-5,12,smooth(a/1.5))
        for ob in wire_objects: ob.hide_render=a>1.7
        # The chip copy has its own moving reflectance field.
        for mat in chip_materials.values():
            for n in mat.node_tree.nodes:
                if n.type=='TEX_NOISE' and n.noise_dimensions=='4D': n.inputs['W'].default_value=t*.85
        chip.rotation_euler=(lerp(.50,0,ease(a/.65)),lerp(-.30,0,ease(a/.65)),0)
        s=lerp(.50,1,ease(a/.65))
        chip.scale=(s,s,s)
        camera.location.z=lerp(20,13,smooth((a-.7)/2.7))
        if a>3.25:
            camera.location.z=lerp(13,1.2,smooth((a-3.25)/.7))
        rim.data.energy=1800
    elif t < 14.2:
        show_type('4K')
        a=t-12.4
        type_root.scale=(lerp(1.8,1,ease(a/.30)),lerp(1.8,1,ease(a/.30)),1)
    elif t < 17.0:
        groups['grid'].hide_render=False
        a=t-14.2
        s=lerp(1.28,1,ease(a/.30))
        grid.scale=(s,s,s)
        grid.rotation_euler=(0,0,0)
        grid.location.y=-2.9*smooth((a-2.22)/.58)
    elif t < 20.1:
        groups['hero'].hide_render=False
        a=t-17
        hero.scale=(.88,.88,.88)
        hero.rotation_euler=(.7-.18*smooth(a/3),-.45+.4*smooth(a/3),.25)
        hero.location=(0,0,0)
        camera.location.z=lerp(13.3,18.5,ease(a/1.3))
        point(camera,(0,0,0))
    else:
        show_type('H3LOOM')
        a=t-20.1
        s=lerp(1.35,.90,ease(a/.5))
        type_root.scale=(s,s,s)
        type_root.location.y=.4

def prepare_storyboard_images():
    """Four original rendered viewpoints, used only as conceptual storyboard art."""
    global current
    old = (scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage)
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 800, 450, 100
    for i, rotation in enumerate([(0,0,0),(.65,-.35,.28),(.88,.35,-.25),(.35,.2,-.1)]):
        set_time(.5)
        hero.rotation_euler=rotation
        hero.scale=(.80,.80,.80) if i!=2 else (1.5,1.5,1.5)
        camera.location.z=16
        path=OUT / ('storyboard-%d.png'%i)
        scene.render.filepath=str(path)
        bpy.ops.render.render(write_still=True)
        m=bpy.data.materials.new('Original rendered board %d'%i)
        m.use_nodes=True
        n=m.node_tree.nodes
        n.clear()
        output=n.new('ShaderNodeOutputMaterial')
        image=n.new('ShaderNodeTexImage')
        image.image=bpy.data.images.load(str(path), check_existing=False)
        emission=n.new('ShaderNodeEmission')
        m.node_tree.links.new(image.outputs['Color'],emission.inputs['Color'])
        m.node_tree.links.new(emission.outputs[0],output.inputs['Surface'])
        current=groups['boards']
        bpy.ops.mesh.primitive_plane_add(size=2, location=(0,0,.135))
        plane=move_group(bpy.context.object)
        plane.name='Original code-rendered storyboard image'
        plane.scale=(2.27,1.00,1)
        plane.data.materials.append(m)
        plane.parent=cards[i]
    scene.render.resolution_x,scene.render.resolution_y,scene.render.resolution_percentage=old

prepare_storyboard_images()

stills=[.35,1.45,2.9,3.8,5.8,7.85,9.3,11.4,12.9,15.0,18.3,21.2]
if opts.stills:
    for t in stills:
        set_time(t)
        scene.render.filepath=str(OUT / ('still-%05.2f.png'%t))
        bpy.ops.render.render(write_still=True)
else:
    for frame in range(opts.start,opts.end):
        dest=OUT / ('frame-%05d.png'%frame)
        if dest.exists(): continue
        set_time(frame/FPS)
        scene.render.filepath=str(dest)
        bpy.ops.render.render(write_still=True)
        print('FILM_FRAME',frame,flush=True)
