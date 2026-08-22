import { Editor } from '@tinymce/tinymce-react';

import 'tinymce/tinymce';
import 'tinymce/icons/default';
import 'tinymce/models/dom/model';
import 'tinymce/themes/silver';

import 'tinymce/plugins/advlist';
import 'tinymce/plugins/anchor';
import 'tinymce/plugins/autolink';
import 'tinymce/plugins/charmap';
import 'tinymce/plugins/code';
import 'tinymce/plugins/fullscreen';
import 'tinymce/plugins/help';
import 'tinymce/plugins/help/js/i18n/keynav/en';
import 'tinymce/plugins/image';
import 'tinymce/plugins/insertdatetime';
import 'tinymce/plugins/link';
import 'tinymce/plugins/lists';
import 'tinymce/plugins/preview';
import 'tinymce/plugins/quickbars';
import 'tinymce/plugins/searchreplace';
import 'tinymce/plugins/table';
import 'tinymce/plugins/visualblocks';
import 'tinymce/plugins/wordcount';

import 'tinymce/skins/ui/oxide/skin';
import 'tinymce/skins/ui/oxide/content';
import 'tinymce/skins/content/default/content';

const NO_EXTERNAL_EDITOR_SCRIPTS = Object.freeze([]);

const SelfHostedEditor = (props) => (
  <Editor
    {...props}
    licenseKey="gpl"
    tinymceScriptSrc={NO_EXTERNAL_EDITOR_SCRIPTS}
  />
);

export default SelfHostedEditor;
