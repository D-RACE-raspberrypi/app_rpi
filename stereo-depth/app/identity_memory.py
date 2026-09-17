"""OSNet appearance memory; immutable anchor and negative examples, no ID-only reacquisition."""
import numpy as np


def similarity(a,b):
    if a is None or b is None:return 0.
    a=np.asarray(a).ravel();b=np.asarray(b).ravel()
    if a.shape!=b.shape:return 0.
    return float(np.dot(a,b)/max(1e-8,np.linalg.norm(a)*np.linalg.norm(b)))


class IdentityMemory:
    def __init__(self):self.clear();self.serial=0
    def clear(self):
        self.gallery=[];self.track=None;self.last_seen=None;self.pending=None;self.hits=0;self.state='none';self.score=None;self.negatives=[];self.last_box=None
    def select(self,track,features,now,negatives=()):
        self.clear();self.serial+=1;self.track=track;self.last_seen=now
        self.gallery=[features] if features is not None else [];self.state='visible';self.negatives=[n for n in negatives if n is not None]
    def update(self,people,features,now,threshold=.92):
        if self.track is None:return None
        gap=now-self.last_seen
        if gap>60:self.state='reselect';return None
        scored=sorted([(max((similarity(features.get(p['id']),g) for g in self.gallery),default=0.),p['id']) for p in people],reverse=True)
        self.state='lost'
        if not scored:self.pending=None;self.hits=0;return None
        score,track=scored[0];self.score=round(score,3)
        margin=score-(scored[1][0] if len(scored)>1 else 0.)
        continuous=track==self.track and gap<.5
        # Never reacquire from the numeric tracker ID alone. No gallery => manual reselection.
        negative=max((similarity(features.get(track),n) for n in self.negatives),default=0.)
        anchor=similarity(features.get(track),self.gallery[0]) if self.gallery else 0.
        if score<(max(.5,threshold-.07) if continuous else threshold) or anchor<(max(.5,threshold-.12) if continuous else max(.5,threshold-.02)) or margin<.12 or score-negative<.12:
            self.state='ambiguous' if score>=.80 else 'lost';self.pending=None;self.hits=0;return None
        if not continuous and any(features.get(p['id']) is None for p in people):
            self.state='ambiguous';self.hits=0;return None
        if not continuous:
            self.hits=self.hits+1 if self.pending==track else 1;self.pending=track
            self.state='confirming'
            if self.hits<6:return None
        self.track=track;self.last_seen=now;self.state='visible';self.pending=None;self.hits=0
        # Preserve original anchor and limit gallery drift; only add near-anchor views.
        feature=features.get(track)
        if feature is not None and self.gallery and similarity(feature,self.gallery[0])>.95 and score>.97:
            self.gallery=(self.gallery[:1]+self.gallery[1:]+[feature])[-8:] if len(self.gallery)<8 else self.gallery[:1]+self.gallery[2:]+[feature]
        return track
