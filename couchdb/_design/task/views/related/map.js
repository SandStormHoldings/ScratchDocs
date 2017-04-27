function (doc) {
    var em=[];
    em.push(doc.creator);
    if (em.indexOf(doc.assignee)==-1) em.push(doc.assignee);
    if (doc.informed) {
	for (var i=0;i<doc.informed.length;i++) {
	    if (em.indexOf(doc.informed[i])==-1)
		em.push(doc.informed[i]);
	}
    }
  for (var i=0;i<em.length;i++) emit(em[i],doc);

}
