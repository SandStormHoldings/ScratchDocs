function (doc) {
    if (doc.informed) {
	for (var i=0;i<doc.informed.length;i++)
	{
	    if (doc.informed[i]!=doc.creator &&
		doc.informed[i]!=doc.assignee)
		emit(doc.informed[i],doc);
	}
    }
}
