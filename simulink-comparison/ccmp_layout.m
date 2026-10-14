function report = ccmp_layout(output)
% User-requested layout: named short connections and obstacle-aware routing.
% This changes diagram geometry only; model_edit owns all structural edits.
if nargin==0, output=fileparts(mfilename('fullpath')); end
top='MotorTunerComparison'; shared='MotorFOCShared';
for model={top,shared}
    set_param(model{1},'SampleTimeColors','off','SampleTimeAnnotations','off');
    hilite_system(model{1},'none');
    blocks=find_system(model{1},'SearchDepth',1,'Type','block');blocks(strcmp(blocks,model{1}))=[];
    for k=1:numel(blocks),set_param(blocks{k},'Orientation','right');end
end
scopes=[{top};find_system(top,'LookUnderMasks','none','FollowLinks','off','BlockType','SubSystem'); ...
    {shared};find_system(shared,'LookUnderMasks','none','FollowLinks','off','BlockType','SubSystem')];
keep=true(size(scopes));
for n=1:numel(scopes)
    if strcmp(scopes{n},top)||strcmp(scopes{n},shared),continue;end
    properties=get_param(scopes{n},'ObjectParameters');
    keep(n)=strcmp(get_param(scopes{n},'Mask'),'off') && ...
        ~(isfield(properties,'SFBlockType') && ~isempty(get_param(scopes{n},'SFBlockType')));
end
scopes=scopes(keep);
for n=1:numel(scopes)
    blocks=find_system(scopes{n},'SearchDepth',1,'Type','block');blocks(strcmp(blocks,scopes{n}))=[];
    for k=1:numel(blocks)
        set_param(blocks{k},'ForegroundColor','black','FontSize','10');
        if ismember(get_param(blocks{k},'BlockType'),{'SubSystem','ModelReference'})
            set_param(blocks{k},'ContentPreviewEnabled','off');
        end
    end
end
for n=1:numel(scopes)
    if ~strcmp(scopes{n},top) && ~strcmp(scopes{n},shared)
        Simulink.BlockDiagram.arrangeSystem(scopes{n});
    end
end
% Compact top-level groups. Named Goto/From blocks carry all feedback.
positions={1,[40 40 145 70];2,[180 45 275 65];3,[40 110 145 140];4,[180 115 275 135]; ...
5,[170 275 315 430];19,[350 345 465 365]; ...
20,[535 215 675 255];25,[380 225 490 245];26,[715 225 830 245]; ...
27,[535 295 675 335];32,[380 305 490 325];33,[715 305 830 325]; ...
34,[535 375 675 415];39,[380 385 490 405];40,[715 385 830 405]; ...
41,[535 455 675 495];46,[380 465 490 485];47,[715 465 830 485]; ...
48,[535 545 675 575];49,[715 550 830 570]; ...
50,[880 275 995 300];51,[1050 350 1080 520]; ...
57,[1160 390 1295 455];63,[1055 565 1170 585];64,[1210 560 1245 590];65,[1350 415 1460 435]; ...
66,[830 105 940 165];72,[665 125 785 145];73,[1060 70 1250 235]; ...
74,[680 55 775 75];75,[830 50 905 80];76,[890 210 1000 230]; ...
77,[1310 87 1420 107];78,[1310 142 1420 162];79,[1310 197 1420 217]};
for n=1:5
    positions(end+1,:)={13+n,[40 282+(n-1)*29 135 302+(n-1)*29]}; %#ok<AGROW>
    positions(end+1,:)={51+n,[885 350+(n-1)*34 1010 370+(n-1)*34]}; %#ok<AGROW>
end
for n=0:5
    positions(end+1,:)={80+2*n,[1510 285+n*54 1625 305+n*54]}; %#ok<AGROW>
    positions(end+1,:)={81+2*n,[1680 285+n*54 1710 305+n*54]}; %#ok<AGROW>
end
place(top,positions);
% Keep the reference engineering shape: inputs, FOC, inverter, PMSM, probes.
place(shared,{1318,[740 210 970 610];366,[1050 305 1160 365];363,[1220 310 1360 390]; ...
362,[1430 260 1590 430];1384,[1640 250 1780 410];1372,[1880 615 1886 725]; ...
1365,[400 390 435 410];1366,[580 465 620 485];1367,[580 495 620 515]; ...
1368,[1330 245 1370 265];1369,[1920 525 1955 545];1370,[1950 660 1985 680];1371,[1050 440 1085 460]; ...
530,[310 250 350 270];531,[310 285 350 305];532,[310 320 350 340]; ...
666,[400 245 450 275];667,[400 280 450 310];668,[400 315 450 345]; ...
720,[530 245 610 275];721,[530 280 610 310];722,[530 315 610 345]; ...
528,[400 350 450 375];725,[530 350 610 380]; ...
1306,[400 415 450 440];1307,[530 415 610 445];1331,[530 385 610 410]; ...
1334,[400 445 450 465];1347,[650 425 700 455];1338,[400 535 450 555];1337,[650 480 700 510]; ...
365,[1120 405 1170 435];1309,[1650 495 1720 525];1332,[1780 495 1840 515];375,[1920 580 1980 610]; ...
682,[1640 440 1710 470];686,[1720 395 1790 425];685,[1710 440 1770 470];688,[1820 410 1870 450]; ...
382,[1830 265 1880 285];383,[1830 305 1880 325];384,[1830 345 1880 365];687,[2010 420 2060 440];719,[2140 470 2200 500]; ...
1378,[1750 620 1830 640];1379,[1750 660 1830 680];1380,[1750 700 1830 720]; ...
1381,[1770 525 1850 545];1382,[1770 585 1850 605];1383,[1920 470 1990 490]});
% Align each prepared feedback signal to its actual FOC input-port height.
ports=get_param(Simulink.ID.getFullName([shared ':1318']),'PortHandles');
portY=zeros(10,1);for n=1:10,p=get_param(ports.Inport(n),'Position');portY(n)=p(2);end
for n=1:3
    place(shared,{529+n,[310 portY(n)-9 350 portY(n)+9];665+n,[400 portY(n)-10 450 portY(n)+10];719+n,[530 portY(n)-10 610 portY(n)+10]});
end
place(shared,{528,[400 portY(4)-9 450 portY(4)+9];725,[530 portY(4)-10 610 portY(4)+10]; ...
1306,[400 portY(5)-9 450 portY(5)+9];1307,[530 portY(5)-10 610 portY(5)+10]; ...
1365,[400 portY(6)-8 435 portY(6)+8];1331,[530 portY(6)-10 610 portY(6)+10]; ...
1334,[400 portY(7)-8 450 portY(7)+8];1347,[530 portY(7)-10 610 portY(7)+10]; ...
1338,[400 portY(8)-8 450 portY(8)+8];1337,[530 portY(8)-10 610 portY(8)+10]; ...
1366,[530 portY(9)-8 570 portY(9)+8];1367,[530 portY(10)-8 570 portY(10)+8]});
place(shared,{686,[1830 385 1900 415];685,[1830 445 1890 475];688,[1950 410 2000 450];1383,[2020 470 2090 490]});
% Uniform native narrow bars; measurement extraction has a white subsystem.
for n=1:numel(scopes)
    bars=find_system(scopes{n},'SearchDepth',1,'BlockType','Mux');
    bars=[bars;find_system(scopes{n},'SearchDepth',1,'BlockType','Demux');find_system(scopes{n},'SearchDepth',1,'BlockType','BusSelector')];
    for k=1:numel(bars)
        p=get_param(bars{k},'Position');ports=get_param(bars{k},'Ports');height=max(32,18*(max(ports(1:2))-1));
        center=[mean(p([1 3])) mean(p([2 4]))];
        set_param(bars{k},'Position',round([center(1)-3 center(2)-height/2 center(1)+3 center(2)+height/2]));
        if strcmp(get_param(bars{k},'BlockType'),'BusSelector'),set_param(bars{k},'ShowName','off');end
    end
    terminals=find_system(scopes{n},'SearchDepth',1,'BlockType','Terminator');
    for k=1:numel(terminals),set_param(terminals{k},'ShowName','off');end
end
for n=1:numel(scopes)
    tags=[find_system(scopes{n},'SearchDepth',1,'BlockType','Goto');find_system(scopes{n},'SearchDepth',1,'BlockType','From')];
    for k=1:numel(tags),set_param(tags{k},'ShowName','off');end
end
% Leave an explicit text line below the top trigger label before SpeedRef.
speedBlock=Simulink.ID.getFullName([shared ':1311']);
set_param(speedBlock,'Position',[175 402 335 762]);
speedPorts=get_param(speedBlock,'PortHandles'); inputSids=[1321 1322 1364 1373 1374];
for n=1:5
    p=get_param(speedPorts.Inport(n),'Position');
    place(shared,{inputSids(n),[80 p(2)-8 120 p(2)+8]});
end
p=get_param(speedPorts.Inport(3),'Position');
place(shared,{1364,[-10 p(2)-8 120 p(2)+8]});
p=get_param(speedPorts.Outport,'Position');place(shared,{1375,[390 p(2)-8 420 p(2)+8]});
% Reset stale branch anchors after resizing the speed PI subsystem.
line=get_param(speedPorts.Outport,'Line'); junction=p+[20 0];
set_param(line,'Points',[p;junction]);
currentBlock=Simulink.ID.getFullName([shared ':727']);
currentPorts=get_param(currentBlock,'PortHandles'); currentRect=get_param(currentBlock,'Position');
currentInput=get_param(currentPorts.Inport(6),'Position');
children=get_param(line,'LineChildren');
for child=children(:)'
    destination=get_param(child,'DstPortHandle'); finish=get_param(destination,'Position');
    if destination==currentPorts.Inport(6)
        x=currentRect(1)-22;y=currentRect(4)+18;
        set_param(child,'Points',[junction;junction(1) y;x y;x currentInput(2);currentInput]);
    else
        set_param(child,'Points',[junction;finish]);
    end
end
resetGoto=Simulink.ID.getFullName([shared ':1362']);
r=get_param(resetGoto,'Position');set_param(resetGoto,'Position',[r(1:2) r(1)+140 r(4)]);
speedRefPort=get_param(speedPorts.Inport(1),'Position');speedPosition=get_param(speedBlock,'Position');
triggerLabelGap=speedRefPort(2)-(speedPosition(2)+14);
assert(triggerLabelGap>=14,'Comparison:TriggerLabel','Insufficient trigger and SpeedRef label spacing');
rows=struct([]);
for n=1:numel(scopes)
    scope=scopes{n}; repair_routes(scope,strcmp(scope,top)||strcmp(scope,shared));
    row=struct('scope',scope,'line_through_block_count',count_crossings(scope), ...
        'block_overlap_count',count_overlaps(scope));
    if isempty(rows),rows=row;else,rows(end+1)=row;end %#ok<AGROW>
end
report=struct('standard_named_Goto_From_feedback',true,'scopes',rows, ...
    'total_line_through_block_count',sum([rows.line_through_block_count]), ...
    'total_block_overlap_count',sum([rows.block_overlap_count]), ...
    'subsystem_content_previews_disabled',true,'sample_time_coloring_disabled',true, ...
    'Trigger_to_SpeedRef_label_clearance_px',triggerLabelGap);
if ~isfolder(fullfile(output,'diagrams')),mkdir(fullfile(output,'diagrams'));end
for n=1:numel(scopes)
    name=regexprep(scopes{n},'[^a-zA-Z0-9_]','_');
    print(['-s' scopes{n}],'-dpng','-r135',fullfile(output,'diagrams',[name '.png']));
    % Library icon redraw can change port geometry; audit after rendering.
    repair_routes(scopes{n},strcmp(scopes{n},top)||strcmp(scopes{n},shared));
    rows(n).line_through_block_count=count_crossings(scopes{n});
    rows(n).block_overlap_count=count_overlaps(scopes{n});
    if rows(n).line_through_block_count==0
        print(['-s' scopes{n}],'-dpng','-r135',fullfile(output,'diagrams',[name '.png']));
        rows(n).line_through_block_count=count_crossings(scopes{n});
    end
end
report.scopes=rows;report.total_line_through_block_count=sum([rows.line_through_block_count]);
report.total_block_overlap_count=sum([rows.block_overlap_count]);
fid=fopen(fullfile(output,'diagram_layout_report.json'),'w');fwrite(fid,jsonencode(report,PrettyPrint=true));fclose(fid);
assert(report.total_line_through_block_count==0,'Comparison:Layout','Lines still pass through blocks');
assert(report.total_block_overlap_count==0,'Comparison:Layout','Block rectangles overlap');
end

function count=count_overlaps(scope)
rectangles=block_rectangles(scope);count=0;
for n=1:size(rectangles,1)-1
    others=rectangles(n+1:end,:);
    count=count+sum(all(max(rectangles(n,1:2),others(:,1:2))<min(rectangles(n,3:4),others(:,3:4)),2));
end
end

function place(model,positions)
for n=1:size(positions,1)
    p=Simulink.ID.getFullName(sprintf('%s:%d',model,positions{n,1}));
    set_param(p,'Position',positions{n,2});
end
end

function count=count_crossings(scope)
rectangles=block_rectangles(scope); lines=find_system(scope,'FindAll','on','SearchDepth',1,'Type','line');
count=0;
for line=lines(:)'
    points=get_param(line,'Points');
    if crosses(points,rectangles),count=count+1;end
end
end

function rectangles=block_rectangles(scope)
blocks=find_system(scope,'SearchDepth',1,'Type','block'); blocks(strcmp(blocks,scope))=[];
rectangles=zeros(numel(blocks),4);
for n=1:numel(blocks),rectangles(n,:)=get_param(blocks{n},'Position');end
end

function repair_routes(scope,routeEveryLine)
rectangles=block_rectangles(scope); lines=find_system(scope,'FindAll','on','SearchDepth',1,'Type','line');
for attempt=1:3
    for line=lines(:)'
        points=get_param(line,'Points');
        if size(points,1)<2 || (~routeEveryLine && ~crosses(points,rectangles)),continue;end
        if any(all(points(1,:)>rectangles(:,1:2)+1 & points(1,:)<rectangles(:,3:4)-1,2)) || ...
                any(all(points(end,:)>rectangles(:,1:2)+1 & points(end,:)<rectangles(:,3:4)-1,2))
            continue
        end
        routed=route(points(1,:),points(end,:),rectangles);
        if ~isempty(routed),set_param(line,'Points',routed);end
    end
end
end

function yes=crosses(points,rectangles)
yes=false;
for k=1:size(points,1)-1
    a=points(k,:);b=points(k+1,:);
    if a(1)==b(1)
        hit=a(1)>rectangles(:,1)+1 & a(1)<rectangles(:,3)-1 & ...
            max(a(2),b(2))>rectangles(:,2)+1 & min(a(2),b(2))<rectangles(:,4)-1;
    elseif a(2)==b(2)
        hit=a(2)>rectangles(:,2)+1 & a(2)<rectangles(:,4)-1 & ...
            max(a(1),b(1))>rectangles(:,1)+1 & min(a(1),b(1))<rectangles(:,3)-1;
    else
        hit=false(size(rectangles,1),1);
        for r=1:size(rectangles,1)
            lo=max(min(a,b),rectangles(r,1:2)+1);hi=min(max(a,b),rectangles(r,3:4)-1);
            if all(lo<hi),hit(r)=true;end
        end
    end
    if any(hit),yes=true;return;end
end
end

function points=route(start,finish,rectangles)
% Manhattan visibility grid, shortest path with a small bend penalty.
if isequal(start,finish),points=[start;finish];return;end
xs=unique([start(1) finish(1) rectangles(:,1)'-14 rectangles(:,3)'+14]);
ys=unique([start(2) finish(2) rectangles(:,2)'-14 rectangles(:,4)'+14]);
[X,Y]=ndgrid(xs,ys); nodes=[X(:),Y(:)]; blocked=false(size(nodes,1),1);
for r=1:size(rectangles,1)
    blocked=blocked | all(nodes>rectangles(r,1:2)+1 & nodes<rectangles(r,3:4)-1,2);
end
s=find(all(nodes==start,2));target=find(all(nodes==finish,2));
score=inf(size(blocked));score(s)=0; parent=zeros(size(blocked)); done=blocked;
while true
    priority=score+sum(abs(nodes-finish),2);priority(done)=inf;
    [value,index]=min(priority); if ~isfinite(value),points=[];return;end
    if index==target,break;end
    done(index)=true;[ix,iy]=ind2sub(size(X),index);
    pairs=[ix-1 iy;ix+1 iy;ix iy-1;ix iy+1];
    pairs=pairs(pairs(:,1)>=1 & pairs(:,1)<=size(X,1) & pairs(:,2)>=1 & pairs(:,2)<=size(X,2),:);
    for n=1:size(pairs,1)
        j=sub2ind(size(X),pairs(n,1),pairs(n,2));
        if done(j) || crosses([nodes(index,:);nodes(j,:)],rectangles),continue;end
        cost=sum(abs(nodes(index,:)-nodes(j,:)));
        if parent(index)>0
            before=nodes(index,:)-nodes(parent(index),:); after=nodes(j,:)-nodes(index,:);
            if (before(1)==0)~=(after(1)==0),cost=cost+8;end
        end
        if score(index)+cost<score(j),score(j)=score(index)+cost;parent(j)=index;end
    end
end
ids=target;while ids(1)~=s,ids=[parent(ids(1));ids];end %#ok<AGROW>
points=nodes(ids,:);keep=[true;any(diff(sign(diff(points,1,1)),1,1)~=0,2);true];points=points(keep,:);
end
