function (doc) {
    var mx = doc.created_at;
    var cr = doc.creator;
    var s = doc.summary;
    for (var i=0;i<doc.journal.length;i++)
    {
	if (doc.journal[i].created_at>mx)
	{
	    mx = doc.journal[i].created_at;
	    cr = doc.journal[i].creator;
	    if (doc.journal[i].content)
		s = doc.journal[i].content.split("\n")[0];
	    else
		s = '';
	}
    }
    emit(mx,[doc._id,doc.tags,cr,s,doc.journal.length]);
    
}
