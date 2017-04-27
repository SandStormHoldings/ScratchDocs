function (doc) {
    if (!(typeof doc.handled_by === undefined) && doc.handled_by) {
	    emit(doc.handled_by,doc);
    }
}