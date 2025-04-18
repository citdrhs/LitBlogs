{/* Media Buttons */}
                <div className="flex gap-2">
                  {/* Image Upload/Camera */}
                  <div className="relative">
                    <input
                      type="file"
                      accept="image/*"
                      capture="environment"
                      onChange={handleImageUpload}
                      className="hidden"
                      id="camera-capture"
                    />
                    <input
                      type="file"
                      accept="image/*"
                      onChange={handleImageUpload}
                      className="hidden"
                      id="image-upload"
                    />
                    <div className="flex gap-2">
                      {/* File Upload Button */}
                      <label htmlFor="image-upload" className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded cursor-pointer" title="Upload Image">
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                        </svg>
                      </label>
                      
                      {/* Camera Capture Button */}
                      <label htmlFor="camera-capture" className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded cursor-pointer" title="Take Photo">
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z" />
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 13a3 3 0 11-6 0 3 3 0 016 0z" />
                        </svg>
                      </label>
                    </div>
                  </div>

                  {/* Video Upload */}
                  <input
                    type="file"
                    accept="video/*"
                    onChange={handleVideoUpload}
                    className="hidden"
                    id="video-upload"
                  />
                  <label htmlFor="video-upload" className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded cursor-pointer">
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                    </svg>
                  </label>

                  {/* File Upload */}
                  <input
                    type="file"
                    onChange={handleFileUpload}
                    className="hidden"
                    id="file-upload"
                  />
                  <label htmlFor="file-upload" className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded cursor-pointer">
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
                    </svg>
                  </label>

                  {/* Divider */}
                  <button type="button" onClick={insertDivider} className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded">
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 12h16M4 6h16M4 18h16" />
                    </svg>
                  </button>

                  {/* Emoji */}
                  <div className="relative">
                    <button type="button" onClick={() => setShowEmojiPicker(!showEmojiPicker)} className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded">
                      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M14.828 14.828a4 4 0 01-5.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                    </button>
                    {showEmojiPicker && (
                      <div className="absolute bottom-full right-0 mb-2">
                        <EmojiPicker onEmojiClick={handleEmojiClick} />
                      </div>
                    )}
                  </div>

                  {/* GIF */}
                  <div className="relative">
                    <button 
                      type="button" 
                      onClick={() => setShowGifPicker(!showGifPicker)} 
                      className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded font-medium"
                    >
                      GIF
                    </button>
                    {showGifPicker && (
                      <div className="absolute bottom-full right-0 mb-2 bg-white dark:bg-gray-800 p-4 rounded-lg shadow-xl" style={{ width: '320px' }}>
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-sm text-gray-500 dark:text-gray-400">
                            Safe Search Enabled
                          </span>
                          <span className="px-2 py-1 text-xs bg-green-100 text-green-800 rounded">
                            School Safe
                          </span>
                        </div>
                        <input
                          type="text"
                          value={gifSearchTerm}
                          onChange={(e) => {
                            setGifSearchTerm(e.target.value);
                            if (e.target.value) {
                              searchGifs(e.target.value);
                            }
                          }}
                          placeholder="Search school-appropriate GIFs..."
                          className={`w-full p-2 mb-2 rounded border ${
                            darkMode 
                              ? 'bg-gray-700 border-gray-600 text-white' 
                              : 'bg-white border-gray-300'
                          }`}
                        />
                        <div className="max-h-60 overflow-y-auto">
                          <div className="grid grid-cols-2 gap-2">
                            {gifs.map((gif) => (
                              <div 
                                key={gif.id} 
                                className="cursor-pointer hover:opacity-80"
                                onClick={() => handleGifSelect(gif)}
                              >
                                <img
                                  src={gif.images.fixed_height_small.url}
                                  alt="GIF"
                                  className="rounded w-full h-auto"
                                  loading="lazy"
                                />
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Expandable List */}
                  <button type="button" onClick={insertExpandableList} className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded">
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 6h16M4 12h16m-7 6h7" />
                    </svg>
                  </button>

                  {/* Poll */}
                  <button type="button" onClick={() => setShowPollForm(!showPollForm)} className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded">
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                    </svg>
                  </button>

                  {/* Code Snippet */}
                  <button 
                    type="button" 
                    onClick={() => setShowCodeEditor(true)} 
                    className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded"
                  >
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
                    </svg>
                  </button>
                </div>

                {/* Poll Form */}
                {showPollForm && (
                  <div className="mt-4 p-4 bg-gray-50 dark:bg-gray-700 rounded-lg">
                    <h3 className="text-lg font-medium mb-4">Create Poll</h3>
                    {pollOptions.map((option, index) => (
                      <input
                        key={index}
                        type="text"
                        value={option}
                        onChange={(e) => {
                          const newOptions = [...pollOptions];
                          newOptions[index] = e.target.value;
                          setPollOptions(newOptions);
                        }}
                        placeholder={`Option ${index + 1}`}
                        className="mb-2 w-full p-2 rounded border"
                      />
                    ))}
                    <button
                      type="button"
                      onClick={() => setPollOptions([...pollOptions, ''])}
                      className="text-blue-500 hover:text-blue-600 mt-2"
                    >
                      + Add Option
                    </button>
                    <div className="flex justify-end mt-4">
                      <button
                        type="button"
                        onClick={handlePollSubmit}
                        className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600"
                      >
                        Add Poll
                      </button>
                    </div>
                  </div>
                )}

                {/* Code Editor */}
                {showCodeEditor && (
                  <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
                    <div className={`${
                      darkMode ? 'bg-gray-800' : 'bg-white'
                    } rounded-lg p-6 max-w-2xl w-full shadow-xl max-h-[80vh] flex flex-col`}>
                      <div className="flex-shrink-0">
                        <h3 className={`text-lg font-medium mb-4 ${
                          darkMode ? 'text-white' : 'text-gray-900'
                        }`}>
                          Add Code Snippet
                        </h3>
                        
                        <select
                          value={codeLanguage}
                          onChange={(e) => setCodeLanguage(e.target.value)}
                          className={`w-full p-2 mb-4 rounded-lg border ${
                            darkMode 
                              ? 'bg-gray-700 border-gray-600 text-white' 
                              : 'bg-white border-gray-300'
                          }`}
                        >
                          <option value="javascript">JavaScript</option>
                          <option value="python">Python</option>
                          <option value="java">Java</option>
                          <option value="cpp">C++</option>
                          <option value="csharp">C#</option>
                          <option value="html">HTML</option>
                          <option value="css">CSS</option>
                          <option value="sql">SQL</option>
                        </select>
                      </div>

                      <div className="flex-1 min-h-0 mb-4">
                        <textarea
                          value={codeContent}
                          onChange={(e) => setCodeContent(e.target.value)}
                          placeholder="Paste your code here..."
                          className={`w-full h-full p-4 rounded-lg border font-mono ${
                            darkMode 
                              ? 'bg-gray-700 border-gray-600 text-white' 
                              : 'bg-white border-gray-300'
                          } resize-none overflow-auto`}
                          style={{ minHeight: "150px", maxHeight: "calc(60vh - 200px)" }}
                        />
                      </div>

                      <div className="flex-shrink-0 flex justify-end gap-4 pt-4 border-t border-gray-200 dark:border-gray-700">
                        <button
                          type="button"
                          onClick={() => {
                            setShowCodeEditor(false);
                            setCodeContent('');
                          }}
                          className={`px-4 py-2 rounded-lg ${
                            darkMode 
                              ? 'bg-gray-700 hover:bg-gray-600 text-white' 
                              : 'bg-gray-200 hover:bg-gray-300 text-gray-900'
                          }`}
                        >
                          Cancel
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            handleCodeSubmit();
                            setShowCodeEditor(false);
                          }}
                          className={`px-4 py-2 rounded-lg text-white ${
                            darkMode ? 'bg-teal-600 hover:bg-teal-500' : 'bg-blue-600 hover:bg-blue-700'
                          }`}
                        >
                          Insert Code
                        </button>
                      </div>
                    </div>
                  </div>
                )} 