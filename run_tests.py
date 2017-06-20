from __future__ import print_function
from builtins import range
#!/usr/bin/env python
import unittest
import config_test as cfg
import docs
import os
from docs import gso 
class TestTask(unittest.TestCase):
    def __init__(self,tc):
        docs.initvars(cfg)
        if not os.path.exists(cfg.DATADIR): os.mkdir(cfg.DATADIR)
        st,op = gso('rm -rf %s/*'%cfg.DATADIR) ; assert st==0
        unittest.TestCase.__init__(self,tc)
    def test_iteration_creation(self):
        docs.add_iteration('testiter')
        rt = docs.add_task('testiter',parent=None,params={'summary':'1st test task'},tags=['chuckacha'])
        tf = docs.get_fns(iteration='testiter',flush=True)
        assert len(tf)==1
        for i in range(5):
            rt2 = docs.add_task(iteration=None,parent=rt['id'],params={'summary':'1st subtask'},tags=['subtask'])
            print(rt2)
            tf = docs.get_fns(iteration='testiter',recurse=True,flush=True)
            assert len(tf)==i+2
        t1 = docs.get_task(rt['id'],read=True)
        assert t1['id']==rt['id']
        assert t1['summary']=='1st test task'
        assert 'chuckacha' in t1['tags']
        t2 = docs.get_task(rt2['id'],read=True)
        assert t2['summary']=='1st subtask'
        assert 'subtask' in t2['tags']
    def setUp(self):
        pass
if __name__=='__main__':
    unittest.main()
