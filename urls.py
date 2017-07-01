# -*- coding: utf-8 -*-
'''
filedesc: default url mapping
'''
from routes import Mapper
from config import DEBUG,URL_PREFIX,METASTATE_URLS
from noodles.utils.maputils import urlmap,include
from routes.route import Route
import os

def get_map():
    " This function returns mapper object for dispatcher "
    mp = Mapper()
    # Add routes here

    taskmaps = [
                (URL_PREFIX+'/s/{task:[\d\/]+}/commits','controllers#task_commits'),
                (URL_PREFIX+'/s/{task:[\d\/]+}/validate','controllers#validate_save'),
                (URL_PREFIX+'/s/{task:[\d\/]+}/show_in_gantt','controllers#show_in_gantt'),
                (URL_PREFIX+'/s/{task:[\d\/]+}/log','controllers#history'),
                (URL_PREFIX+'/s/{task:[\d\/]+}/j','controllers#journal'),
                (URL_PREFIX+'/s/{task:[\d\/]+}/j/{jid}','controllers#journal_edit'),
                (URL_PREFIX+'/s/{task:((new/|)[\d\/]+)}','controllers#task'),
                (URL_PREFIX+'/s/{task:([\d\/]+)}/c','controllers#task_changes'),
                (URL_PREFIX+'/s/{task:([\d\/]+)}/rev/{rev:.*}','controllers#task'),        
    ]
    taskmaps+=([(t[0].replace('/s/','/'),t[1]) for t in taskmaps])



    urlmap(mp, [
        (URL_PREFIX+'/s/new','controllers#task',{'task':'new'}), # new top level task handler

        (URL_PREFIX+'/commits/{repo:.*}/{rev:.*}','controllers#commit_validity'),
        (URL_PREFIX+'/', 'controllers#index'),
        (URL_PREFIX+'/test', 'controllers#test'),
        (URL_PREFIX+'/tr', 'controllers#index',{'gethours':True}),

        (URL_PREFIX+'/karma','controllers#karma'),
        
        (URL_PREFIX+'/incoming','controllers#incoming'),
        (URL_PREFIX+'/incoming/{tags:.*}','controllers#incoming'),

        (URL_PREFIX+'/metastates','controllers#metastates'),
        (URL_PREFIX+'/metastates/tags-{tags:([^/]*)}/{state:.*}','controllers#metastate'),
        (URL_PREFIX+'/metastates/tags-{tags:.*}','controllers#metastates'),
        (URL_PREFIX+'/metastates/{state:.*}','controllers#metastate'),
        
        (URL_PREFIX+'/feed', 'controllers#feed'),
        (URL_PREFIX+'/feed/fs', 'controllers#feed_fs'),
        (URL_PREFIX+'/feed/{user}', 'controllers#feed'),
        (URL_PREFIX+'/feed/{user}/fs', 'controllers#feed_fs'),

        (URL_PREFIX+'/journal', 'controllers#global_journal'),
        (URL_PREFIX+'/journal/groupby/{groupby}', 'controllers#global_journal'),

        (URL_PREFIX+'/metastate-set','controllers#metastate_set'),

        (URL_PREFIX+'/tl', 'controllers#top_level'),
        (URL_PREFIX+'/st', 'controllers#storage'),
        (URL_PREFIX+'/participants', 'controllers#participants'),
        (URL_PREFIX+'/tags', 'controllers#tags'),
        (URL_PREFIX+"/tag-pri",'controllers#tag_pri'),
        (URL_PREFIX+'/tag/{tag}', 'controllers#bytag'),

        (URL_PREFIX+'/pri','controllers#prioritization'),
        
        # tasks go here.

        (URL_PREFIX+'/search','controllers#search'),
        (URL_PREFIX+'/favicon.ico', 'controllers#favicon'),
        (URL_PREFIX+'/assets/{r_type}/{r_file}', 'controllers#assets'),

        (URL_PREFIX+"/g","controllers#gantt"),
        (URL_PREFIX+"/g/save","controllers#gantt_save"),

        (URL_PREFIX+"/tt","controllers#time_tracking_dashboard"),
        (URL_PREFIX+"/tt/{rangeback:.*}/{persons:.*}","controllers#time_tracking_dashboard"),                
        (URL_PREFIX+"/tt/{rangeback:.*}","controllers#time_tracking_dashboard"),

        (URL_PREFIX+"/ttt","controllers#time_tracking_dashboard",{'mode':'tid'}),        
        (URL_PREFIX+"/ttt/{rangeback:.*}/{tids:([\d\/,]+)}","controllers#time_tracking_dashboard",{'mode':'tid'}),                
    ])

    for tm in taskmaps:
        mp.connect(None,tm[0],
                   controller=tm[1].split('#')[0],
                   action=tm[1].split('#')[1])
    
    for pf,gethours in list({'/tr':True,'':False}.items()):
        mp.connect(None,URL_PREFIX+'/assignments/{person}'+pf, controller='controllers',action='assignments',gethours=gethours)
        mp.connect(None,URL_PREFIX+'/a/{person}'+pf, controller='controllers',action='assignments',gethours=gethours) # synonym to /assignments
        mp.connect(None,URL_PREFIX+'/created/{person}'+pf, controller='controllers',action='created',gethours=gethours),
        mp.connect(None,URL_PREFIX+'/informed/{person}'+pf, controller='controllers',action='informed',gethours=gethours),
        mp.connect(None,URL_PREFIX+'/handled_by/{person}'+pf, controller='controllers',action='handled_by',gethours=gethours),
        mp.connect(None,URL_PREFIX+'/assignments/{person}/{mode}'+pf, controller='controllers',action='assignments_mode',gethours=gethours)
        mp.connect(None,URL_PREFIX+'/latest'+pf, controller='controllers',action='latest',gethours=gethours),
        mp.connect(None,URL_PREFIX+'/latest/{max_days}'+pf, controller='controllers',action='latest',gethours=gethours)
        
    for msabbr,msgroup in list(METASTATE_URLS.items()):

        def mcnt(msabbr,mp):
            url = URL_PREFIX+'/'+msabbr
            # (URL_PREFIX+'/q', 'controllers#queue',{'assignee':'me'}),
            mp.connect(None,url,controller='controllers',action='queue',metastate_group=msgroup,assignee='me')
            # (URL_PREFIX+'/q/archive', 'controllers#queue',{'assignee':'me','archive':True}),
            mp.connect(None,url+'/archive',controller='controllers',action='queue',assignee='me',archive=True,metastate_group=msgroup)
            # (URL_PREFIX+'/q/assignee/{assignee}', 'controllers#queue'),
            mp.connect(None,url+'/assignee/{assignee}',controller='controllers',action='queue',metastate_group=msgroup)
            # (URL_PREFIX+'/q/assignee/{assignee}/archive', 'controllers#queue',{'archive':True}),
            mp.connect(None,url+'/assignee/{assignee}/archive',controller='controllers',action='queue',metastate_group=msgroup,archive=True)
            # (URL_PREFIX+'/q/all', 'controllers#queue'),
            mp.connect(None,url+'/all',controller='controllers',action='queue',metastate_group=msgroup)
            # (URL_PREFIX+'/q/all/archive', 'controllers#queue',{'archive':True}),
            mp.connect(None,url+'/all/archive',controller='controllers',action='queue',metastate_group=msgroup,archive=True)
            return mp

        mp = mcnt(msabbr,mp)

    filters = ['day','creator','state']
    for flt in filters:
        url = URL_PREFIX+'/journal/filter'
        def mcnt(url,flt,mp,chain=[]):
            url+='/%s/{%s}'%(flt,flt)
            #print 'connecting',url
            mp.connect(None,url,controller='controllers',action='global_journal')
            mp.connect(None,url+'/groupby/{groupby}',controller='controllers',action='global_journal')
            chain.append(flt)
            for flt2 in filters:
                if flt2 not in chain:
                    mcnt(url,flt2,mp,chain)
            return mp
        mp = mcnt(url,flt,mp)


        
    return mp
