function(doc) {
    if (doc.external_msg_id != undefined)
    {
	emit(doc.external_msg_id,doc._id);
    }
}
