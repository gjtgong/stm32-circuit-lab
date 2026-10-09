"""Bounded EasyEDA Standard schematic/PCB terminal-partition comparison.

Uses pin dots, straight W segments, J junctions, N/F labels and O no-connect
flags. Interior crossings without a connection anchor are not joined. This
is not general ERC or a device electrical model.
"""
import argparse,json,hashlib,os
from collections import defaultdict,Counter
from pathlib import Path


def schematic_graph(document):
    nodes={};parent=[]
    def node(point):
        key=tuple(round(float(v),9) for v in point)
        if key not in nodes:nodes[key]=len(parent);parent.append(len(parent))
        return nodes[key]
    def find(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    def join(a,b):parent[find(a)]=find(b)
    def xy(fields):return (float(fields[0]),float(fields[1]))
    segments=[];pins={};labels=[];nc=[];ignored=Counter();components={}
    def record(shape,ref=None):
        fields=shape.split('~');kind=fields[0]
        if kind=='W':
            values=list(map(float,fields[1].split()))
            if len(values)<4 or len(values)%2:raise ValueError('Invalid wire coordinates')
            points=list(zip(values[::2],values[1::2]))
            for a,b in zip(points,points[1:]):
                if a==b:continue
                join(node(a),node(b));segments.append((a,b))
        elif kind=='P':
            if not ref:raise ValueError('Pin lacks component reference')
            parts=shape.split('^^');position=xy(parts[1].split('~'))
            number=parts[4].split('~')[4];name=parts[3].split('~')[4]
            key=f'{ref}:{number}'
            if key in pins:raise ValueError('Duplicate schematic terminal '+key)
            pins[key]={'ref':ref,'number':number,'name':name,'id':fields[7],'node':node(position),'x':position[0],'y':position[1]}
        elif kind=='N':labels.append((fields[5],node(xy(fields[1:3]))))
        elif kind=='F':
            parts=shape.split('^^');labels.append((parts[2].split('~')[0],node(xy(parts[1].split('~')))))
        elif kind=='J':node(xy(fields[1:3]))
        elif kind=='O':nc.append((fields[3],node(xy(fields[1:3]))))
        elif kind in ('B','BE'):raise ValueError('Bus/hierarchy semantics unsupported')
        elif kind in ('T','PL','PT','R','E','A','PG','C','L','I','PI','AR','Pimage'):ignored[kind]+=1
        else:raise ValueError('Unsupported schematic record '+kind)
    for shape in document['shape']:
        if shape.startswith('LIB~'):
            parts=shape.split('#@$')
            ref=next((p.split('~')[12] for p in parts[1:] if p.startswith('T~P~')),'')
            if any(child.startswith('P~') for child in parts[1:]):
                component_id=parts[0].split('~')[6]
                if component_id in components:raise ValueError('Duplicate schematic component ID')
                components[component_id]=ref
            for child in parts[1:]:record(child,ref)
        else:record(shape)
    # Anchor-driven joining: endpoints, pin dots, labels, explicit junctions.
    # No synthetic nodes at arbitrary interior wire crossings.
    for point,index in nodes.items():
        for a,b in segments:
            dx,dy=b[0]-a[0],b[1]-a[1]
            t=((point[0]-a[0])*dx+(point[1]-a[1])*dy)/(dx*dx+dy*dy)
            if -1e-9<=t<=1+1e-9 and abs((point[0]-a[0])*dy-(point[1]-a[1])*dx)/(dx*dx+dy*dy)**.5<=1e-6:join(index,node(a))
    named=defaultdict(list)
    for name,index in labels:
        if not name:raise ValueError('Empty net label')
        named[name].append(index)
    for indices in named.values():
        for index in indices[1:]:join(indices[0],index)
    names=defaultdict(set);terminals=defaultdict(list);flags=defaultdict(list)
    for name,index in labels:names[find(index)].add(name)
    for key,pin in pins.items():terminals[find(pin['node'])].append(key)
    for id,index in nc:flags[find(index)].append(id)
    conflicts=[]
    for root,members in terminals.items():
        if flags[root] and (len(members)>1 or names[root]):conflicts.append({'type':'no_connect_is_connected','terminals':members,'labels':sorted(names[root]),'flags':flags[root]})
        for key in members:
            pins[key].update(group=root,labels=sorted(names[root]),noConnectFlags=flags[root],noConnect=bool(flags[root]) and len(members)==1 and not names[root])
            pins[key].pop('node')
    aliases=[{'labels':sorted(values),'terminals':terminals[root],'requiresReview':True} for root,values in names.items() if len(values)>1]
    orphan=[{'id':id} for root,ids in flags.items() if not terminals[root] for id in ids]
    return {'components':components,'labelAliasGroups':aliases,'pins':pins,'groups':{root:sorted(keys) for root,keys in terminals.items()},'issues':conflicts,'orphanNoConnectFlags':orphan,'coverage':{'pins':len(pins),'wireSegments':len(segments),'labels':len(labels),'noConnectFlags':len(nc),'ignoredGraphicRecords':dict(ignored)}}


def compare(board,graph):
    pcb=defaultdict(list);unmapped=[];referenceAliases=[]
    identities=graph.get('components',{})
    refs={}
    for component in board.get('components',[]):
        ref=identities.get(component['id'],component.get('ref'))
        refs[component['id']]=ref
        if ref and component.get('ref')!=ref:referenceAliases.append({'componentId':component['id'],'pcbRef':component.get('ref'),'schematicRef':ref,'basis':'same source component ID'})
    for pad in board.get('pads',[]):
        ref=refs.get(pad.get('componentId'),pad.get('ref'))
        if not ref or not str(pad.get('number') or ''):unmapped.append(pad['id']);continue
        pcb[f"{ref}:{pad['number']}"].append(pad)
    pins=graph['pins'];common=set(pcb)&set(pins);issues=[];statuses=[];groups=defaultdict(list)
    for key in sorted(common):
        pin=pins[key];pads=pcb[key];nets={p['net'] for p in pads if p.get('net')}
        if len(nets)>1:
            issues.append({'type':'duplicate_terminal_network_conflict','terminal':key,'pcbNets':sorted(nets)})
            state='mismatch'
        elif pin['noConnect']:
            if nets:issues.append({'type':'no_connect_has_pcb_net','terminal':key,'pcbNets':sorted(nets)})
            state='explicit-no-connect' if not nets else 'mismatch'
        elif not nets:
            state='missing-pcb-net';issues.append({'type':'schematic_pin_missing_pcb_net','terminal':key,'schematicLabels':pin['labels'],'schematicGroup':graph['groups'][pin['group']]})
        else:
            state='mapped';groups[pin['group']].append((key,next(iter(nets))))
            if pin['labels'] and not nets.intersection(pin['labels']):
                state='mismatch'
                issues.append({'type':'label_mismatch','terminal':key,'schematicLabels':pin['labels'],'pcbNets':sorted(nets)})
        statuses.append({'terminal':key,'state':state,'pinName':pin['name'],'schematicLabels':pin['labels'],'noConnectFlags':pin['noConnectFlags'],'pcbNets':sorted(nets),'padIds':[p['id'] for p in pads]})
    for root,members in groups.items():
        nets={net for _,net in members}
        if len(nets)>1:issues.append({'type':'schematic_net_split_in_pcb','terminals':[key for key,_ in members],'pcbNets':sorted(nets)})
    inverse=defaultdict(lambda:defaultdict(list))
    for root,members in groups.items():
        for key,net in members:inverse[net][root].append(key)
    for net,parts in inverse.items():
        if len(parts)>1:issues.append({'type':'pcb_net_merges_schematic_groups','pcbNet':net,'terminalGroups':list(parts.values())})
    return {'experimental':True,'complete':False,'summary':{'schematicPins':len(pins),'matchedTerminals':len(common),'explicitNoConnectMatched':sum(s['state']=='explicit-no-connect' for s in statuses),'networkIssues':len(issues),'schematicIssues':len(graph['issues']),'labelAliasGroups':len(graph['labelAliasGroups']),'missingPcbTerminals':len(set(pins)-set(pcb)),'extraPcbTerminals':len(set(pcb)-set(pins)),'unmappedPcbPads':len(unmapped),'orphanNoConnectFlags':len(graph['orphanNoConnectFlags'])},'referenceAliases':referenceAliases,'labelAliasGroups':graph['labelAliasGroups'],'networkIssues':issues,'schematicIssues':graph['issues'],'terminalStatus':statuses,'missingPcbTerminals':sorted(set(pins)-set(pcb)),'extraPcbTerminals':sorted(set(pcb)-set(pins)),'unmappedPcbPadIds':unmapped,'orphanNoConnectFlags':graph['orphanNoConnectFlags'],'coverage':graph['coverage'],'limitations':['Bounded single-sheet EasyEDA Standard straight-wire graph; unsupported bus/hierarchy rejected.','Compare assigned PCB nets, not physical Gerber conductivity; run both checks.','Component/pin identity uses source references and pin numbers; unmapped pads require review.','Explicit O flag means schematic intent only, not verification against device datasheets.','Not general ERC, voltage/current/thermal or manufacturing validation.']}


def main():
    import import_open_board as converter
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--schematic',type=Path,default=converter.ROOT/'references/open-board/EasyEDA_project-with-schematic.api.json')
    parser.add_argument('--output',type=Path,default=Path('reports/schematic-check.json'))
    args=parser.parse_args();result=json.loads(args.schematic.read_text())['result'];sheets=result['schematics']
    if len(sheets)!=1:raise ValueError('Only single-sheet schematic supported')
    document=sheets[0]['dataStr'];document=json.loads(document) if isinstance(document,str) else document
    report=compare(converter.parse_board(),schematic_graph(document))
    inputs=[args.schematic,converter.DEFAULT_SOURCE]
    report['inputHashes']={os.path.relpath(p.resolve(),converter.ROOT):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report['summary'],ensure_ascii=False));print('Experimental comparison; no electrical pass verdict. Report:',args.output)
if __name__=='__main__':main()
