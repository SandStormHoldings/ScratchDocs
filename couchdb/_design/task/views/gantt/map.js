function (doc) {
    if (['REVIEW','DOING','TODO','DONE'].indexOf(doc.status)!=-1)
    {
	var weat=null;
	var we=null;
	for (var i=0;i<doc.journal.length;i++)
	{
	    var je = doc.journal[i];
	    if (je.attrs['work estimate'] &&
		je.created_at>=weat || !weat)
		we=je.attrs['work estimate'];
	}
	if (we)
	    emit(doc._id,[doc._id,
			  doc.created_at,
			  doc._id+': '+doc.summary,
			  0,
			  we,
			  0,
			  null,
			  doc.g_links]);
    }
}
