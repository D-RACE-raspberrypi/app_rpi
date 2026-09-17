import time
import threading
import numpy as np
import pytest
from following import Follower, measure_person, validate
from hailo_backend import decode_people, letterbox
from app import Engine, create_app

P=np.array([[100.,0,100],[0,100,50],[0,0,1]])
R=np.eye(3)


def test_bearing_rotation_and_mounting():
    box=[.7,.1,.9,.9]
    a=measure_person(box,None,P,R,(200,100),False,0)
    b=measure_person(box,None,P,R,(200,100),True,0)
    assert a['bearing_deg']==pytest.approx(31,abs=.1)
    assert b['bearing_deg']>0
    assert measure_person(box,None,P,R,(200,100),True,10)['bearing_deg']==pytest.approx(b['bearing_deg']+10)
    assert measure_person([.1,.1,.3,.9],None,P,R,(200,100),True,0)['bearing_deg']<0
    assert a['distance_m'] is None


def test_range_uses_only_torso_and_rejects_sparse_mixed_depth():
    depth=np.full((100,200),8.,np.float32)
    box=[.2,.1,.8,.9]
    depth[26:58,76:124]=2
    result=measure_person(box,depth,P,R,(200,100),False,0)
    assert result['distance_m']==2
    assert result['forward_m']==2
    depth[26:58,76:124]=np.nan
    assert measure_person(box,depth,P,R,(200,100),False,0)['distance_m'] is None
    depth[26:58,76:100]=2
    depth[26:58,100:124]=5
    assert measure_person(box,depth,P,R,(200,100),False,0)['distance_m'] is None


def test_undo_rectification_for_bearing():
    angle=np.deg2rad(10)
    rotation=np.array([[np.cos(angle),0,np.sin(angle)],[0,1,0],[-np.sin(angle),0,np.cos(angle)]])
    result=measure_person([.4,.1,.6,.9],None,P,rotation,(200,100),False,0)
    assert result['bearing_deg']==-10


def test_letterbox_rgb_and_inverse_coordinate_mapping():
    frame=np.zeros((100,200,3),np.uint8);frame[:]=[10,20,30]
    image,pad=letterbox(frame,(640,640))
    assert pad==(0,160,640,320)
    assert image[200,100].tolist()==[30,20,10]
    nms=[np.empty((0,5)) for _ in range(80)]
    nms[0]=np.array([[.3,.1,.7,.9,.8],[0,0,1,1,.1]])
    nms[1]=np.array([[0,0,1,1,.99]])
    people=decode_people(nms,(640,640),pad,.45)
    assert len(people)==1
    assert people[0]['box']==pytest.approx([.1,.1,.9,.9])
    with pytest.raises(ValueError): decode_people(nms[:1],(640,640),pad,.4)


@pytest.mark.parametrize('config',[{'target_m':float('nan')},{'enabled':1},{'confidence':True},{'camera_yaw_deg':100},{'unknown':2}])
def test_invalid_settings(config):
    with pytest.raises(ValueError):validate(config)


def seed(follower, people=None):
    follower.state='ready'
    follower.result=dict(captured_at=time.monotonic(),people=people or [dict(id=7,box=[.1,.1,.3,.9],distance_m=2)],image=None)


def test_selection_loss_staleness_and_no_automatic_switch(tmp_path):
    f=Follower(tmp_path);seed(f)
    f.select(7,f.generation)
    assert f.snapshot()['target']['distance_error_m']==.5
    f.result['people']=[dict(id=8,box=[.1,.1,.3,.9],distance_m=2)]
    assert f.snapshot()['target'] is None
    assert f.snapshot()['selected_id']==7
    f.selected_seen-=61
    assert f.snapshot()['selection_state']=='reselect'
    seed(f)
    assert f.snapshot()['target'] is None
    f.select(7,f.generation)
    f.result['captured_at']-=1.1
    assert f.snapshot()['target'] is None
    with pytest.raises(ValueError):f.select(7,f.generation)


def test_geometry_change_invalidates_selection_and_rejects_old_click(tmp_path):
    f=Follower(tmp_path);seed(f);f.select(7,0)
    image=np.zeros((100,200,3),np.uint8)
    f.submit(image,None,P,R,True,True,time.monotonic(),3)
    assert f.snapshot()['selected_id'] is None
    seed(f)
    with pytest.raises(ValueError): f.select(7,0)


def test_worker_keeps_same_frame_depth_and_drops_inflight_on_change(tmp_path):
    entered=threading.Event();release=threading.Event()
    class Backend:
        def infer(self,image,threshold):
            entered.set();release.wait(2)
            return [dict(id=1,box=[.2,.1,.8,.9],confidence=.9)]
        def close(self):pass
    f=Follower(tmp_path,Backend);f.start()
    image=np.zeros((100,200,3),np.uint8);depth=np.full((100,200),2.,np.float32)
    try:
        f.submit(image,depth,P,R,False,True,time.monotonic(),1)
        assert entered.wait(1)
        f.configure({'target_m':2.5})
        release.set()
        time.sleep(.05)
        assert f.result is None
        f.submit(image,depth,P,R,False,True,time.monotonic(),1)
        deadline=time.monotonic()+2
        while f.result is None and time.monotonic()<deadline:time.sleep(.01)
        result=f.snapshot()
        assert result['people'][0]['distance_m']==2
        assert result['image'] and result['approximate']
    finally:release.set();f.stop()


def test_following_api_without_hailo_and_settings_persist(tmp_path):
    e=Engine(tmp_path);client=create_app(e).test_client()
    response=client.get('/api/following')
    assert response.status_code==200 and response.json['motor_control'] is False
    assert client.post('/api/following/settings',json={'target_m':2,'camera_yaw_deg':-5}).status_code==200
    assert Follower(tmp_path).config['camera_yaw_deg']==-5
    assert client.post('/api/following/settings',json=[]).status_code==400
    assert client.post('/api/following/select',json={'id':1,'generation':0}).status_code==400
    assert client.post('/api/following/select',json={'id':None,'generation':0}).status_code==200


def test_native_hailo_tracker_keeps_identity_on_stationary_person():
    hailo=pytest.importorskip('hailo')
    import uuid
    from hailo_backend import create_tracker
    name='regression-'+uuid.uuid4().hex
    tracker=create_tracker(hailo,name)
    history=[]
    try:
        for _ in range(30):
            people=tracker.update(name,[hailo.HailoDetection(hailo.HailoBBox(.2,.1,.4,.8),0,'person',.95)])
            ids=[obj.get_id() for person in people for obj in person.get_objects_typed(hailo.HAILO_UNIQUE_ID)]
            history.append(ids)
        assert all(len(ids)==1 for ids in history[3:])
        assert len({ids[0] for ids in history[3:]})==1
    finally:tracker.remove_jde_tracker(name)


def test_mask_excludes_occluder_and_trimmed_mean_accepts_noise():
    box=[.2,.1,.8,.9];depth=np.full((100,200),.7,np.float32)
    mask=np.zeros((100,200),np.uint8);mask[20:65,80:115]=1
    rng=np.random.default_rng(1);depth[20:65,80:115]=2+rng.normal(0,.15,(45,35))
    r=measure_person(box,depth,P,R,(200,100),False,0,mask=mask)
    assert r['distance_m']==pytest.approx(2,abs=.1)
    assert 'masque' in r['depth_method']
    assert measure_person(box,depth,P,R,(200,100),False,0,mask=np.zeros_like(mask))['distance_m'] is None


def test_beyond_range_needs_valid_depth():
    box=[.2,.1,.8,.9]
    r=measure_person(box,np.full((100,200),5.,np.float32),P,R,(200,100),False,0,far=4)
    assert r['distance_status']=='beyond_range'
    assert r['distance_m']==4
    r=measure_person(box,np.full((100,200),np.nan),P,R,(200,100),False,0)
    assert r['distance_m'] is None
    assert r.get('distance_status')!='beyond_range'
