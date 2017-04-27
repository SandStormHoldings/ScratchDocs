function (doc) {
    var ms = {};
    var lchange=null;
    for (var i=0;i<doc.journal.length;i++)
    {
	var je = doc.journal[i];
	for (var an in je.attrs)
	{
	    if (['unq_key','work estimate'].indexOf(an)!=-1) continue;

	    var putin=false;
	    var av = je.attrs[an];
	    if (an in ms)
	    {
		if (!ms[an].ts || (ms[an].ts<=je.created_at))
		{
		    putin=true;

		}
	    }
	    else
		putin=true;

	    if (putin)
	    {
		ms[an]={'v':av,'ts':je.created_at};
		if (!lchange || je.created_at>lchange) lchange=je.created_at;
	    }
	}
    }
    var cr = doc.created_at;
    for (var k in ms)
    {
	emit([k,ms[k]['v']],[doc._id,cr,lchange,doc.tags]);
    }
    emit(['status',doc.status],[doc._id,cr,lchange,doc.tags]);

}